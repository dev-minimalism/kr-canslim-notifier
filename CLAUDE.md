# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

한국 주식 피벗 돌파 신호 탐지 시스템입니다. 감시 종목(watchlist)을 pykrx로 주기적으로 스캔해 돌파 패턴을 감지하고, 텔레그램으로 알림을 보내며, 신호 발생 시 가상 포지션(paper trading)을 자동 기록/청산합니다.

## Commands

```bash
cp .env.example .env            # set TELEGRAM_TOKEN, CHAT_ID
pip install -e ".[dev]"

python -m kr_canslim_notifier           # run bot (also: kr-canslim-notifier)
python -m kr_canslim_notifier backtest  # backtest over watchlist.json
python -m kr_canslim_notifier init-db   # create PostgreSQL tables

pytest                                   # tests/ currently has no tests
pytest tests/test_foo.py::test_bar       # single test
black src/ && ruff check src/
```

## Dependency Notes

- pykrx is pinned `>=1.2.9`: 1.0.x does `import pkg_resources` and fails in setuptools-less Python 3.12 venvs. An old venv may still have 1.0.x → `pip install -U pykrx`.
- pykrx 1.2.x prints `KRX 로그인 실패: KRX_ID 또는 KRX_PW ...` at import when those env vars are unset. Harmless: the two calls used here (`get_market_ohlcv_by_date`, `get_market_ticker_name`) work without login.
- `.gitignore` ignores `/config.py` at the repo root only; `backtest/config.py` (`BacktestConfig`, reads `BACKTEST_*` env vars, tickers from `watchlist.json`) is tracked source.

## Architecture

Everything runs in one process with two threads, plus one for each manual scan:

1. **Main loop** (`__main__.run_bot`): calls `BreakoutDetector.run_scheduled_scan()` every `SCAN_INTERVAL` seconds (default 1800). Outside market hours it only runs `check_positions()`.
2. **Command listener** (`start_command_listener`, daemon thread): long-polls Telegram `getUpdates` and only handles messages whose chat id matches `CHAT_ID`. `process_command` returns either a reply string or the sentinel `"SCAN"`. `"SCAN"` starts `_execute_scan_in_thread` in a new daemon thread. Manual and scheduled scans both take `scan_lock` with a non-blocking acquire and set `is_scanning`. If a scan is already running, the other one is skipped. Any new code path that scans must take `scan_lock`.

Position state has its own lock, `positions_lock` (an `RLock`):
- `add_position()` and `close_position()` take it internally; the `_add_position` / `_close_position` bodies assume it is held.
- `close_position()` returns `False` if the position is no longer open, so a scan and `/close` on the listener thread can't close the same position twice.
- Code running on the listener thread must never reassign `self.positions`. `/positions` reads into a local list.
- `repository.close()` also uses `WHERE status = 'open'` with `UPDATE` and `INSERT` in one transaction, so a second close is a no-op even across processes.

`bot.py` (`BreakoutDetector`) holds nearly all the logic: watchlist, positions, Telegram I/O, data fetching, signal detection and scanning.

**Scan flow** (`run_scan`): `check_positions()` (exits for stop-loss / take-profit / 30 days held) → for each watchlist ticker not already held: `get_stock_data` (pykrx OHLCV, Korean column names renamed to `Open/High/Low/Close/Volume`) → `detect_pivot_breakout` → on a signal: `add_position` at the current price first. The alert goes out only if the position was saved; otherwise the next scan retries the stock. After a successful DB write, `_refresh_positions_after_write()` reloads the list and only logs on failure, so a failed reload can't cancel an alert. Automatic scans only send a summary when there are signals; manual `/scan` always sends one.

**Signal** (`detect_pivot_breakout`): needs ≥30 bars. Close > max of the previous 19 closes, volume ≥ `VOLUME_SURGE_MIN`% above the 29-bar average, and `0 < breakout% ≤ BREAKOUT_MAX`. `backtest/runner.py` (`PivotBreakoutBacktester`) reimplements the strategy on its own, and the two **currently differ**: the backtest uses the highest high of the previous 20 days and a 20-day volume average that includes today. Changes to the signal logic have to be made in both places. The backtest fills gap-through stops and targets at the open, and closes positions still open at `end_date` with reason `백테스트 종료`.

**Storage** has two backends, chosen by `USE_DB` and checked throughout `bot.py` with `if self.use_db:`:
- Positions: JSON (`positions.json`, atomic write through `.tmp` + `os.replace`) or PostgreSQL through `repository.PositionRepository`, which also writes `trade_history` and powers `/stats`. DB modules are imported lazily, so JSON mode doesn't need psycopg2 or sshtunnel. If the DB fails to initialize, the bot prints a warning and **silently falls back to JSON**.
- Watchlist: **always JSON** (`watchlist.json`, `{"tickers": [...]}`; the legacy `{"kr": [...]}` is also read). `WatchlistRepository` and the `watchlist` table exist but aren't used. When no file exists, the default watchlist is `005930, 000660, 035420`.
- `database.py`: `SSHTunnel` (sshtunnel `SSHTunnelForwarder` → random local port) + `DatabaseConnection` (`connect()` pings with `SELECT 1` and reconnects the tunnel and connection if they're dead; `get_cursor()` context manager commits or rolls back; `init_schema()` is idempotent and also runs at bot startup in DB mode). `get_cursor()` retries only the connect step (`_open_cursor`, up to `MAX_RETRIES`). Errors inside the `with` body are re-raised unchanged and never retried, because a `@contextmanager` generator can yield only once; adding a retry loop around `yield` brings back `RuntimeError: generator didn't stop after throw()`. On a connection error the connection is dropped, so the next call reconnects. `get_db()` returns a module-level singleton.

## Gotchas

- Hardcoded vs. configurable: stop-loss −8% (`entry*0.92`), take-profit +20% (`entry*1.20`), 30-day expiry, the 20-day lookback and the 120-day fetch window are all hardcoded in `bot.py`. `STOP_LOSS_PERCENT` and `ANALYSIS_PERIOD_DAYS` exist in `settings.py`/`.env.example` but **nothing reads them**. `WATCHLIST_FILE` is read only by the backtest; the bot always uses `watchlist.json`. In the bot, only `SCAN_INTERVAL`, `VOLUME_SURGE_MIN` and `BREAKOUT_MAX` affect behavior.
- `load_positions()` raises on read failure (DB error or corrupt JSON). `check_positions()` then returns `False` and `run_scan` aborts. Never turn a failed read into `[]`: the "already held" check would pass for every stock and create duplicate alerts and positions.
- For an unknown code, pykrx `get_market_ticker_name` returns an empty DataFrame instead of raising. Always go through `lookup_stock_name()` (returns `None`), `get_stock_name()` or `format_stock()`. Never call pykrx directly for names.
- `is_market_open()` uses naive `datetime.now()` (09:00–15:30, weekdays, no holiday calendar), so it assumes the host runs in KST.
- `settings` is a class with attributes evaluated at import time (`load_dotenv()` runs on import). Env changes made after import have no effect.
- Telegram messages use `parse_mode=HTML`. Escape `<`, `>`, `&` in dynamic text.
- User-facing strings and logs are in Korean with emoji prefixes; follow that style.

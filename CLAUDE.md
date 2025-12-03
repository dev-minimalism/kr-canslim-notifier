# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

한국 주식 피벗 돌파 신호 탐지 시스템입니다. 한국 주식 시장을 모니터링하고, 돌파 패턴을 감지하여 텔레그램으로 알림을 전송합니다.

## Commands

### Setup
```bash
cp .env.example .env
# Edit .env with your TELEGRAM_TOKEN and CHAT_ID
pip install -e .
```

### Run the Bot
```bash
# As module
python -m kr_canslim_notifier

# Or via entry point (after pip install)
kr-canslim-notifier
```

### Development
```bash
pip install -e ".[dev]"
pytest
black src/
ruff check src/
```

## Project Structure

```
kr-canslim-notifier/
├── src/
│   └── kr_canslim_notifier/
│       ├── __init__.py
│       ├── __main__.py      # Entry point (python -m kr_canslim_notifier)
│       ├── bot.py           # BreakoutDetector class
│       ├── settings.py      # Environment variable loading
│       ├── database.py      # SSH tunnel + PostgreSQL connection
│       └── repository.py    # Position/Watchlist DB operations
├── tests/
├── .env.example
├── pyproject.toml
└── CLAUDE.md
```

## Architecture

### Core Modules

**`src/kr_canslim_notifier/bot.py`** - `BreakoutDetector` class:
- Telegram command listener (background thread)
- Korean market time detection (09:00-15:30)
- Position tracking with automatic stop-loss/take-profit
- Concurrent scan prevention via threading lock

**`src/kr_canslim_notifier/settings.py`** - `Settings` class:
- Environment variable loading via python-dotenv
- All configurable parameters with defaults
- SSH/PostgreSQL connection settings

**`src/kr_canslim_notifier/database.py`** - Database connection:
- SSH tunnel via paramiko for remote PostgreSQL
- Connection pooling and context managers
- Schema initialization

**`src/kr_canslim_notifier/repository.py`** - Data access:
- `PositionRepository`: CRUD operations for positions
- `WatchlistRepository`: CRUD operations for watchlist
- Trade history and statistics

### Data Source
- Korean stocks: `pykrx` (price data only)

### Technical Signal
- Pivot breakout: Price breaks 20-day high with 50%+ volume surge, within 5% of breakout level

### Runtime Data Files (gitignored)
- `watchlist.json` - Persisted watchlist (`{"tickers": [...]}` format)
- `positions.json` - Open positions tracking (JSON mode)

### Storage Options
- **JSON mode** (default): Positions stored in `positions.json`
- **PostgreSQL mode** (`USE_DB=true`): Positions stored in PostgreSQL via SSH tunnel

### Telegram Commands
`/scan`, `/add [code]`, `/remove [code]`, `/list`, `/positions`, `/close [code]`, `/stats`, `/status`, `/help`

### CLI Commands
```bash
python -m kr_canslim_notifier           # Run bot
python -m kr_canslim_notifier backtest  # Run backtest
python -m kr_canslim_notifier init-db   # Initialize DB schema
```

## Key Patterns

- Scan operations run in separate threads to avoid blocking the command listener
- Positions auto-close at -8% stop-loss, +20% take-profit, or 30-day expiry
- Market hours: Korean market 09:00-15:30 (weekdays only)
- **Duplicate signal prevention**: Stocks with open positions are skipped during scan (no duplicate alerts)

## Telegram Alerts

| Event | Alert |
|-------|-------|
| New breakout signal (no position) | O |
| Breakout signal (position exists) | X (skipped) |
| Position closed (stop-loss/take-profit/expiry/manual) | O |

## Database Schema (PostgreSQL mode)

```sql
-- positions: Open/closed position tracking
-- trade_history: Completed trades for statistics
-- watchlist: Monitored stock tickers
```

## Environment Variables

```bash
# Required
TELEGRAM_TOKEN=your_bot_token
CHAT_ID=your_chat_id

# Optional - PostgreSQL (USE_DB=true)
SSH_HOST=remote_host
SSH_USER=username
SSH_KEY_PATH=~/.ssh/id_rsa
DB_HOST=localhost
DB_PORT=5432
DB_NAME=database_name
DB_USER=db_user
DB_PASSWORD=db_password
USE_DB=false
```

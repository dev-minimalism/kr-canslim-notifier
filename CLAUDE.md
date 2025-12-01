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
│       └── settings.py      # Environment variable loading
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

### Data Source
- Korean stocks: `pykrx` (price data only)

### Technical Signal
- Pivot breakout: Price breaks 20-day high with 50%+ volume surge, within 5% of breakout level

### Runtime Data Files (gitignored)
- `watchlist.json` - Persisted watchlist (`{"tickers": [...]}` format)
- `positions.json` - Open positions tracking

### Telegram Commands
`/scan`, `/add [code]`, `/remove [code]`, `/list`, `/positions`, `/close [code]`, `/status`, `/help`

## Key Patterns

- Scan operations run in separate threads to avoid blocking the command listener
- Positions auto-close at -8% stop-loss, +20% take-profit, or 30-day expiry
- Market hours: Korean market 09:00-15:30 (weekdays only)

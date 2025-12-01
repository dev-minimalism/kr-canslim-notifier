# 한국 주식 돌파 탐지 봇

한국 주식 시장의 피벗 돌파 패턴을 감지하여 텔레그램으로 알림을 전송하는 시스템입니다.

## Features

- **피벗 돌파 탐지**
  - 20일 고점 돌파
  - 거래량 50%+ 급증
  - 돌파율 0~5% 이내

- **자동 포지션 관리**
  - 손절 -8%, 익절 +20%, 30일 만료

- **텔레그램 봇 연동**
  - 실시간 알림
  - 명령어로 종목 관리

## Installation

```bash
# 저장소 클론
git clone https://github.com/dev-minimalism/kr-canslim-notifier.git
cd kr-canslim-notifier

# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate

# 패키지 설치
pip install -e .

# 환경 설정
cp .env.example .env
# .env 파일에서 TELEGRAM_TOKEN과 CHAT_ID 설정
```

## Usage

### 봇 실행

```bash
# 모듈로 실행
python -m kr_canslim_notifier

# 또는 CLI 명령어
kr-canslim-notifier
```

### 백그라운드 실행 (서버)

```bash
nohup python -m kr_canslim_notifier > bot.log 2>&1 &
```

설명:
- `nohup` - 터미널 종료해도 계속 실행
- `> bot.log` - stdout을 bot.log에 저장
- `2>&1` - stderr도 같은 파일에 저장
- `&` - 백그라운드 실행

날짜별 로그 파일:
```bash
mkdir -p logs
nohup python -u -m kr_canslim_notifier > logs/bot_$(date +%Y%m%d).log 2>&1 &
```

유용한 명령어:
```bash
# 실행 확인
ps aux | grep kr_canslim_notifier

# 로그 실시간 확인
tail -f bot.log

# 프로세스 종료
pkill -f kr_canslim_notifier
```

### 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/scan` | 전체 종목 스캔 |
| `/add 005930` | 종목 추가 |
| `/remove 005930` | 종목 제거 |
| `/list` | 감시 종목 목록 |
| `/positions` | 보유 포지션 보기 |
| `/close 005930` | 포지션 수동 청산 |
| `/status` | 시장 상태 확인 |
| `/help` | 도움말 |

## Backtesting

피벗 돌파 전략 백테스트 기능을 제공합니다.

### 백테스트 실행

```bash
# watchlist.json 전체 종목 백테스트
python -m kr_canslim_notifier backtest
```

### 환경변수로 설정

`.env` 파일에서 백테스트 파라미터 설정:

```env
# 백테스트 기간
BACKTEST_START_DATE=2024-01-01
BACKTEST_END_DATE=2024-12-31

# 자본금
BACKTEST_INITIAL_CAPITAL=10000000

# 전략 파라미터
BACKTEST_LOOKBACK_PERIOD=20
VOLUME_SURGE_MIN=50
BREAKOUT_MAX=5

# 리스크 관리
BACKTEST_STOP_LOSS_PCT=0.08
BACKTEST_TAKE_PROFIT_PCT=0.20
BACKTEST_HOLDING_DAYS_MAX=30
```

### Python에서 사용

```python
from kr_canslim_notifier.backtest import BacktestConfig, run_backtest

# 기본 설정으로 실행
run_backtest()

# 커스텀 설정
config = BacktestConfig(
    start_date="2024-01-01",
    end_date="2024-12-31",
    initial_capital=10_000_000,
    stop_loss_pct=0.08,
    take_profit_pct=0.20,
)
run_backtest(config)
```

## Configuration

`.env` 파일에서 설정:

```env
# 필수
TELEGRAM_TOKEN=your_bot_token
CHAT_ID=your_chat_id

# 선택 (기본값)
SCAN_INTERVAL=1800
VOLUME_SURGE_MIN=50
BREAKOUT_MAX=5
STOP_LOSS_PERCENT=-7.5
ANALYSIS_PERIOD_DAYS=120
```

## Project Structure

```
kr-canslim-notifier/
├── src/kr_canslim_notifier/
│   ├── __main__.py      # 진입점
│   ├── bot.py           # 메인 봇 클래스
│   ├── settings.py      # 환경 설정
│   └── backtest/        # 백테스트 패키지
│       ├── __init__.py
│       ├── config.py    # BacktestConfig
│       └── runner.py    # PivotBreakoutBacktester
├── tests/
├── .env.example
├── pyproject.toml
└── README.md
```

## Data Source

- **한국 주식**: pykrx (가격 데이터)

## License

MIT

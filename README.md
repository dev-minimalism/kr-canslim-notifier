# 한국 주식 돌파 탐지 봇

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![pykrx](https://img.shields.io/badge/pykrx-0A5BAA)](https://github.com/sharebook-kr/pykrx)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)](https://core.telegram.org/bots)

한국 주식 시장의 피벗 돌파 패턴을 감지하여 텔레그램으로 알림을 전송하는 시스템입니다.

## Features

- **피벗 돌파 탐지**
  - 직전 20일 고가 최고점 돌파 (오늘 제외)
  - 거래량이 직전 20일 평균보다 50% 이상 많음 (오늘 제외)
  - 돌파율 0~5% 이내
  - 실전 봇과 백테스트가 같은 판단 코드(`signals.py`)를 사용

- **자동 포지션 관리 (페이퍼 트레이딩)**
  - 매수 신호 발생 시 가상 포지션 자동 기록
  - 손절 -8%, 익절 +20%, 30일 만료 시 자동 청산
  - 이미 보유 중인 종목은 중복 신호 알림 생략

- **텔레그램 봇 연동**
  - 실시간 알림
  - 명령어로 종목 관리

- **저장소 선택**
  - JSON 파일 (기본) 또는 SSH 터널 경유 PostgreSQL

## Installation

Python 3.10 이상이 필요합니다.

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
| `/stats` | 거래 통계 (DB 모드 전용) |
| `/help` | 도움말 |

자동 스캔은 장중(평일 09:00-15:30)에만 실행되며, 새 신호가 있을 때만 알림을 보냅니다. `/scan`은 장 시간과 관계없이 실행되고 항상 완료 메시지를 보냅니다. 장 시간은 서버의 로컬 시간 기준이므로 서버 타임존을 KST로 설정하세요.

## Backtesting

피벗 돌파 전략 백테스트 기능을 제공합니다.

### 백테스트 실행

```bash
# watchlist.json 전체 종목 백테스트
python -m kr_canslim_notifier backtest
```

### 시뮬레이션 규칙

- 매수 신호는 실전 봇과 같은 기준(`signals.py`)으로 판단합니다.
- 종목마다 고정 금액(초기 자본 × `BACKTEST_POSITION_SIZE_PCT`)을 투자합니다.
- 남은 현금이 고정 금액보다 적으면 새 신호를 건너뜁니다. 투자 금액은 자본을 넘지 않습니다.
- 같은 날 신호가 여러 개면 거래량 급증률이 높은 종목부터 삽니다.
- 손절가나 익절가를 갭으로 건너뛰면 시가에 체결합니다.
- 기간이 끝날 때 남은 포지션은 마지막 종가로 청산해 결과에 포함합니다.
- 결과에 최대 동시 보유 종목 수와 건너뛴 신호 수가 나옵니다.

### 환경변수로 설정

`.env` 파일에서 백테스트 파라미터 설정:

```env
# 백테스트 기간
BACKTEST_START_DATE=2024-01-01
BACKTEST_END_DATE=2024-12-31

# 자본금
BACKTEST_INITIAL_CAPITAL=10000000
BACKTEST_POSITION_SIZE_PCT=0.1   # 종목당 투입 비율 (자본금의 10%)

# 전략 파라미터 (VOLUME_SURGE_MIN, BREAKOUT_MAX는 봇과 공유)
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
SCAN_INTERVAL=1800      # 스캔 간격 (초)
VOLUME_SURGE_MIN=50     # 거래량 급증 최소값 (%)
BREAKOUT_MAX=5          # 돌파율 최대값 (%)
```

> `.env.example`의 `STOP_LOSS_PERCENT`, `ANALYSIS_PERIOD_DAYS`는 현재 코드에서 사용되지 않습니다. 손절(-8%), 익절(+20%), 보유 기간(30일)은 코드에 고정되어 있습니다.

### PostgreSQL 모드

기본적으로 포지션은 `positions.json`에 저장됩니다. `USE_DB=true`로 설정하면 SSH 터널을 통해 원격 PostgreSQL에 포지션과 거래 내역(`/stats`)을 저장합니다.

```env
USE_DB=true

SSH_HOST=your_ssh_host
SSH_PORT=22
SSH_USER=your_ssh_user
SSH_KEY_PATH=~/.ssh/id_rsa

DB_HOST=localhost   # SSH 서버 기준 DB 호스트
DB_PORT=5432
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
```

```bash
# 테이블 생성 (봇 시작 시에도 자동 실행됨)
python -m kr_canslim_notifier init-db
```

- 감시 종목(watchlist)은 DB 모드에서도 `watchlist.json`에 저장됩니다.
- 봇 시작 시 DB 연결에 실패하면 경고 후 JSON 모드로 동작합니다.

## Project Structure

```
kr-canslim-notifier/
├── src/kr_canslim_notifier/
│   ├── __main__.py      # 진입점 (bot / backtest / init-db)
│   ├── bot.py           # 메인 봇 클래스 (BreakoutDetector)
│   ├── settings.py      # 환경 설정
│   ├── database.py      # SSH 터널 + PostgreSQL 연결
│   ├── repository.py    # 포지션/거래 내역 DB 접근
│   └── backtest/        # 백테스트 패키지
│       ├── __init__.py
│       ├── config.py    # BacktestConfig
│       └── runner.py    # PivotBreakoutBacktester
├── tests/
├── .env.example
├── pyproject.toml
├── LICENSE
└── README.md
```

## Data Source

- **한국 주식**: [pykrx](https://github.com/sharebook-kr/pykrx) 1.2.9+ (가격 데이터)
  - 실행 시 `KRX 로그인 실패: KRX_ID 또는 KRX_PW 환경 변수가 설정되지 않았습니다.` 메시지가 출력될 수 있습니다. 이 봇이 사용하는 OHLCV/종목명 조회는 로그인 없이 동작하므로 무시해도 됩니다.

## License

[MIT](LICENSE)

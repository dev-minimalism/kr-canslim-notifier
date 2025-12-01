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
git clone https://github.com/dev-minimalism/can-slim-bot.git
cd can-slim-bot

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
python -m can_slim_bot

# 또는 CLI 명령어
can-slim-bot
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
can-slim-bot/
├── src/can_slim_bot/
│   ├── __main__.py      # 진입점
│   ├── bot.py           # 메인 봇 클래스
│   └── settings.py      # 환경 설정
├── tests/
├── .env.example
├── pyproject.toml
└── README.md
```

## Data Source

- **한국 주식**: pykrx (가격 데이터)

## License

MIT

"""Entry point for running the bot as a module: python -m can_slim_bot"""

import time
from datetime import datetime, timedelta

from .bot import BreakoutDetector
from .settings import settings


def main():
    """Main entry point."""
    if not settings.is_configured():
        print("⚠️  .env 파일 설정이 필요합니다:")
        print("   1. .env.example을 .env로 복사")
        print("   2. .env 파일에서 TELEGRAM_TOKEN과 CHAT_ID 설정")
        print("\n종료합니다.\n")
        return

    print("✅ .env 설정 로드 완료\n")

    # Initialize bot
    detector = BreakoutDetector(settings.TELEGRAM_TOKEN, settings.CHAT_ID)

    # Start Telegram command listener
    detector.start_command_listener()

    # Start message
    is_open = detector.is_market_open()
    status_text = "🇰🇷 개장 중" if is_open else "⏸️ 폐장"

    start_msg = f"""
🤖 <b>한국 주식 돌파 탐지 봇 시작</b>

📊 감시 종목: {len(detector.watchlist)}개
📍 보유 포지션: {len(detector.positions)}개

⏰ 스캔 간격: {settings.SCAN_INTERVAL // 60}분
🕐 시장 상태: {status_text}

📈 자동 스캔:
   • 한국 시장 (09:00-15:30)

🎯 자동 포지션 관리:
   • 매수 신호 시 자동 기록
   • 손절 (-8%), 익절 (+20%), 30일 만료

💬 명령어:
   /scan - 종목 스캔
   /positions - 포지션 보기
   /help - 모든 명령어

시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    detector.send_telegram_message(start_msg)
    print(start_msg)

    # Main loop
    try:
        while True:
            detector.run_scheduled_scan()

            next_scan = datetime.now() + timedelta(seconds=settings.SCAN_INTERVAL)
            print(f"⏰ 다음 스캔: {next_scan.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"💤 {settings.SCAN_INTERVAL // 60}분 대기 중...\n")
            time.sleep(settings.SCAN_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n⛔ 종료합니다")
        detector.send_telegram_message("⛔ 한국 주식 돌파 탐지 봇 종료")


if __name__ == "__main__":
    main()

"""
Korean Stock Breakout Detection Bot

Features:
- Pivot point breakout detection
- Telegram command-based stock management
- Position management with stop-loss/take-profit (JSON or PostgreSQL)
- Automatic market hours detection
"""

import json
import os
import threading
import time
import warnings
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from pykrx import stock

from .settings import settings

warnings.filterwarnings("ignore")

# Lazy import for DB modules (only when USE_DB=true)
_position_repo = None
_db = None


def _get_position_repo():
    """Get PositionRepository instance (lazy initialization)."""
    global _position_repo
    if _position_repo is None:
        from .repository import PositionRepository
        _position_repo = PositionRepository()
    return _position_repo


def _get_db():
    """Get DatabaseConnection instance (lazy initialization)."""
    global _db
    if _db is None:
        from .database import get_db
        _db = get_db()
    return _db


class BreakoutDetector:
    """Korean stock breakout pattern detection class."""

    def __init__(
        self,
        telegram_token: str,
        chat_id: str,
        watchlist_file: str = "watchlist.json",
        positions_file: str = "positions.json",
        use_db: bool = None,
    ):
        """
        Initialize the detector.

        Args:
            telegram_token: Telegram bot token
            chat_id: Telegram chat ID
            watchlist_file: Watchlist storage file
            positions_file: Position storage file
            use_db: Use PostgreSQL for positions (default: settings.USE_DB)
        """
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{telegram_token}"
        self.watchlist_file = watchlist_file
        self.positions_file = positions_file
        self.last_update_id = 0

        # Determine storage backend
        self.use_db = use_db if use_db is not None else settings.USE_DB

        # Concurrent scan prevention lock
        self.scan_lock = threading.Lock()
        self.is_scanning = False

        # Guards self.positions and position storage. Scans and /close (listener
        # thread) both close positions; without it one position can close twice.
        # Reentrant because writes refresh the list while holding it.
        self.positions_lock = threading.RLock()

        # Initialize DB if needed
        if self.use_db:
            self._init_db()

        # Load watchlist and positions
        self.watchlist = self.load_watchlist()
        try:
            self.positions = self.load_positions()
        except Exception as e:
            # Each scan reloads positions and aborts if this still fails
            print(f"⚠️  Failed to load positions: {e}")
            self.positions = []

        storage_type = "PostgreSQL" if self.use_db else "JSON"
        print(f"✅ Storage: {storage_type}")
        print("✅ Watchlist loaded")
        print(f"   🇰🇷 종목 수: {len(self.watchlist)}")
        print(f"✅ Positions loaded: {len(self.positions)}")

    def _init_db(self):
        """Initialize database connection and schema."""
        try:
            db = _get_db()
            db.init_schema()
            print("✅ Database initialized")
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            print("⚠️  Falling back to JSON storage")
            self.use_db = False

    # ========================================
    # Watchlist Management
    # ========================================

    def load_watchlist(self) -> List[str]:
        """Load watchlist from file."""
        if os.path.exists(self.watchlist_file):
            try:
                with open(self.watchlist_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Support both old format {"kr": [...]} and new format {"tickers": [...]}
                    if "tickers" in data:
                        return data.get("tickers", [])
                    elif "kr" in data:
                        return data.get("kr", [])
            except Exception as e:
                print(f"⚠️  Failed to load watchlist: {e}")

        # Default watchlist
        return ["005930", "000660", "035420"]

    def save_watchlist(self) -> bool:
        """Save watchlist to file."""
        try:
            data = {
                "tickers": self.watchlist,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            # Atomic write: 임시 파일에 쓴 후 rename (파일 손상 방지)
            tmp_file = self.watchlist_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.watchlist_file)
            return True
        except Exception as e:
            print(f"❌ Failed to save watchlist: {e}")
            return False

    def add_stock(self, ticker: str) -> str:
        """Add stock to watchlist."""
        ticker = ticker.strip()
        if ticker in self.watchlist:
            return f"⚠️  {self.format_stock(ticker)}은 이미 감시 중입니다."

        name = self.lookup_stock_name(ticker)
        if not name:
            return (
                f"❌ 종목을 찾을 수 없습니다: {ticker}\n"
                "6자리 종목코드를 입력해주세요.\n예) /add 005930"
            )

        self.watchlist.append(ticker)
        if self.save_watchlist():
            return f"✅ {name}({ticker}) 추가됨!\n현재 감시 종목: {len(self.watchlist)}개"
        else:
            self.watchlist.remove(ticker)
            return "❌ 저장 실패"

    def remove_stock(self, ticker: str) -> str:
        """Remove stock from watchlist."""
        ticker = ticker.strip()
        if ticker not in self.watchlist:
            return f"⚠️  {ticker}은 감시 목록에 없습니다."

        stock_display = self.format_stock(ticker)

        self.watchlist.remove(ticker)
        if self.save_watchlist():
            return f"✅ {stock_display} 제거됨!\n현재 감시 종목: {len(self.watchlist)}개"
        else:
            self.watchlist.append(ticker)
            return "❌ 저장 실패"

    def list_watchlist(self) -> str:
        """Get watchlist display string."""
        msg = f"📊 <b>감시 종목</b> ({len(self.watchlist)}개)\n\n"

        if self.watchlist:
            msg += "\n".join(self.format_stock(ticker) for ticker in self.watchlist)
        else:
            msg += "감시 종목 없음"

        return msg

    # ========================================
    # Position Management
    # ========================================

    def load_positions(self) -> List[Dict]:
        """Load positions from storage (DB or file).

        Raises on read failure so a failed read is never mistaken for
        "no positions" (which would bypass duplicate signal prevention).
        """
        if self.use_db:
            repo = _get_position_repo()
            return repo.get_all_open()

        # JSON file storage
        if not os.path.exists(self.positions_file):
            return []
        with open(self.positions_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("positions", [])

    def save_positions(self) -> bool:
        """Save positions to file (only for JSON mode)."""
        if self.use_db:
            return True  # DB handles persistence automatically

        try:
            data = {
                "positions": self.positions,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            # Atomic write: 임시 파일에 쓴 후 rename (파일 손상 방지)
            tmp_file = self.positions_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.positions_file)
            return True
        except Exception as e:
            print(f"❌ Failed to save positions: {e}")
            return False

    def _refresh_positions_after_write(self):
        """Reload positions after a successful DB write.

        Only logs on failure: a failed reload must not turn a successful
        write into a failure (that would skip the signal alert).
        """
        try:
            self.positions = self.load_positions()
        except Exception as e:
            print(f"⚠️  Failed to refresh positions: {e}")

    def add_position(
        self, ticker: str, entry_price: float, pattern: str, signal: Dict
    ) -> bool:
        """Add new position.

        Returns:
            True if position was saved successfully, False otherwise.
        """
        with self.positions_lock:
            return self._add_position(ticker, entry_price, pattern, signal)

    def _add_position(
        self, ticker: str, entry_price: float, pattern: str, signal: Dict
    ) -> bool:
        """add_position body. Caller holds positions_lock."""
        if self.use_db:
            try:
                repo = _get_position_repo()
                repo.add(ticker, entry_price, pattern, signal)
            except Exception as e:
                print(f"❌ Failed to add position to DB: {e}")
                return False
            self._refresh_positions_after_write()
            return True

        # JSON file storage
        position = {
            "ticker": ticker,
            "entry_price": entry_price,
            "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pattern": pattern,
            "stop_loss": entry_price * 0.92,  # -8% stop loss
            "take_profit": entry_price * 1.20,  # +20% take profit
            "signal": signal,
        }
        self.positions.append(position)
        if self.save_positions():
            print(f"  📝 Position added: {ticker} @ {entry_price:,}")
            return True
        else:
            # Rollback: remove from memory if save failed
            self.positions.remove(position)
            return False

    def close_position(self, ticker: str, exit_price: float, reason: str) -> bool:
        """Close position.

        Returns:
            True if closed, False if it was not open (e.g. already closed by
            another thread) or the close could not be saved.
        """
        with self.positions_lock:
            return self._close_position(ticker, exit_price, reason)

    def _close_position(self, ticker: str, exit_price: float, reason: str) -> bool:
        """close_position body. Caller holds positions_lock."""
        if self.use_db:
            try:
                repo = _get_position_repo()
                result = repo.close(ticker, exit_price, reason)
            except Exception as e:
                print(f"❌ Failed to close position in DB: {e}")
                return False
            if not result:
                return False
            self._send_close_message(result, reason)
            self._refresh_positions_after_write()
            return True

        # JSON file storage
        for pos in self.positions:
            if pos["ticker"] == ticker:
                entry_price = pos["entry_price"]
                profit_pct = ((exit_price - entry_price) / entry_price) * 100

                entry_date = datetime.strptime(
                    pos["entry_date"], "%Y-%m-%d %H:%M:%S"
                )
                holding_days = (datetime.now() - entry_date).days

                result = {
                    "ticker": ticker,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "profit_pct": profit_pct,
                    "holding_days": holding_days,
                    "pattern": pos.get("pattern"),
                }
                self._send_close_message(result, reason)

                self.positions.remove(pos)
                self.save_positions()
                print(f"  ❌ Position closed: {ticker} ({reason}) {profit_pct:+.2f}%")
                return True
        return False

    def _send_close_message(self, result: Dict, reason: str):
        """Send position close message to Telegram."""
        ticker = result["ticker"]
        entry_price = result["entry_price"]
        exit_price = result["exit_price"]
        profit_pct = result["profit_pct"]
        holding_days = result.get("holding_days", 0)
        pattern = result.get("pattern", "")
        ticker_display = self.format_stock(ticker)

        msg = f"""
🇰🇷 <b>[포지션 종료]</b>

🏢 종목: <b>{ticker_display}</b>
📊 패턴: {pattern}
💰 진입가: {entry_price:,.0f}원
💵 종료가: {exit_price:,.0f}원
{'📈' if profit_pct > 0 else '📉'} 수익률: {profit_pct:+.2f}%
📅 보유일: {holding_days}일

🔔 사유: {reason}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_telegram_message(msg)

    def _parse_entry_date(self, entry_date) -> datetime:
        """Parse entry_date to datetime object."""
        if isinstance(entry_date, datetime):
            return entry_date
        return datetime.strptime(entry_date, "%Y-%m-%d %H:%M:%S")

    def check_positions(self) -> bool:
        """Check and manage open positions.

        Returns:
            False if positions could not be loaded from storage.
        """
        # Refresh positions from storage
        try:
            with self.positions_lock:
                self.positions = self.load_positions()
        except Exception as e:
            print(f"❌ Failed to load positions: {e}")
            return False

        if not self.positions:
            return True

        print(f"\n📊 Checking positions... ({len(self.positions)})")

        for pos in self.positions.copy():
            ticker = pos["ticker"]
            entry_price = float(pos["entry_price"])
            entry_date = self._parse_entry_date(pos["entry_date"])
            holding_days = (datetime.now() - entry_date).days

            try:
                df = self.get_stock_data(ticker, days=7)

                if df is None or len(df) == 0:
                    continue

                current_price = df["Close"].iloc[-1]
                profit_pct = ((current_price - entry_price) / entry_price) * 100

                print(
                    f"  🔍 {ticker}: {current_price:,.0f}원 ({profit_pct:+.2f}%)",
                    end="",
                )

                if current_price <= pos["stop_loss"]:
                    print(" ⚠️ Stop loss!")
                    self.close_position(ticker, current_price, "손절 (-8%)")
                elif current_price >= pos["take_profit"]:
                    print(" ✅ Take profit!")
                    self.close_position(ticker, current_price, "익절 (+20%)")
                elif holding_days >= 30:
                    print(" ⏰ Time exit!")
                    self.close_position(
                        ticker, current_price, f"보유기간 만료 ({holding_days}일)"
                    )
                else:
                    print(" ⚪")

                time.sleep(1)

            except Exception as e:
                print(f" ❌ Error: {e}")

    def list_positions(self) -> str:
        """Get positions display string."""
        # Read into a local list: replacing self.positions here (listener thread)
        # could drop a position a running scan just added
        try:
            positions = self.load_positions()
        except Exception as e:
            return f"❌ 포지션 조회 실패: {e}"

        if not positions:
            return "📊 <b>보유 포지션</b>\n\n보유 중인 포지션이 없습니다."

        msg = f"📊 <b>보유 포지션</b> ({len(positions)}개)\n\n"

        for i, pos in enumerate(positions, 1):
            ticker = pos["ticker"]
            entry_date = self._parse_entry_date(pos["entry_date"])
            holding_days = (datetime.now() - entry_date).days
            ticker_display = self.format_stock(ticker)

            try:
                df = self.get_stock_data(ticker, days=7)

                if df is not None and len(df) > 0:
                    current_price = df["Close"].iloc[-1]
                    profit_pct = (
                        (current_price - pos["entry_price"]) / pos["entry_price"]
                    ) * 100
                    profit_icon = "📈" if profit_pct > 0 else "📉"
                    current_info = f"{current_price:,.0f}원 ({profit_icon}{profit_pct:+.2f}%)"
                else:
                    current_info = "조회 실패"
            except:
                current_info = "조회 실패"

            msg += f"""
{i}. <b>{ticker_display}</b>
   진입가: {pos['entry_price']:,.0f}원
   현재가: {current_info}
   패턴: {pos['pattern']}
   보유일: {holding_days}일
   손절가: {pos['stop_loss']:,.0f}원
   목표가: {pos['take_profit']:,.0f}원
"""

        return msg

    def get_trade_stats(self) -> str:
        """Get trading statistics (DB mode only)."""
        if not self.use_db:
            return "📊 <b>거래 통계</b>\n\n⚠️ 통계 기능은 DB 모드에서만 사용 가능합니다.\n.env에서 USE_DB=true로 설정해주세요."

        try:
            repo = _get_position_repo()
            stats = repo.get_stats()

            if not stats or stats.get("total_trades", 0) == 0:
                return "📊 <b>거래 통계</b>\n\n아직 완료된 거래가 없습니다."

            msg = f"""📊 <b>거래 통계</b>

<b>전체 거래:</b> {stats['total_trades']}건
<b>승리:</b> {stats['winning_trades']}건
<b>패배:</b> {stats['losing_trades']}건
<b>승률:</b> {stats['win_rate']:.1f}%

<b>평균 수익률:</b> {stats['avg_profit_pct']:+.2f}%
<b>총 수익률:</b> {stats['total_profit_pct']:+.2f}%
<b>최대 수익:</b> {stats['max_profit_pct']:+.2f}%
<b>최대 손실:</b> {stats['max_loss_pct']:+.2f}%

<b>평균 보유일:</b> {stats['avg_holding_days']:.1f}일
"""
            return msg

        except Exception as e:
            return f"❌ 통계 조회 오류: {e}"

    # ========================================
    # Market Status
    # ========================================

    def is_market_open(self) -> bool:
        """Check if Korean market is open."""
        now = datetime.now()
        current_time = now.time()
        weekday = now.weekday()

        is_weekend = weekday >= 5

        # Korean market: 09:00 - 15:30 (weekdays)
        kr_open = dt_time(9, 0)
        kr_close = dt_time(15, 30)

        return (not is_weekend) and (kr_open <= current_time <= kr_close)

    def get_market_status(self) -> str:
        """Get market status message."""
        now = datetime.now()
        is_open = self.is_market_open()

        msg = "📊 <b>시장 상태</b>\n\n"
        msg += f"⏰ 현재 시간: {now.strftime('%H:%M:%S')}\n\n"

        if is_open:
            msg += "🇰🇷 한국 시장 <b>개장 중</b> (09:00-15:30)\n"
            msg += f"   감시 종목: {len(self.watchlist)}개\n"
        else:
            msg += "🇰🇷 한국 시장 <b>폐장</b>\n"

        if self.is_scanning:
            msg += "\n🔄 스캔 진행 중..."

        return msg

    # ========================================
    # Telegram
    # ========================================

    def send_telegram_message(self, message: str):
        """Send message via Telegram."""
        try:
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
            response = requests.post(f"{self.base_url}/sendMessage", data=payload)
            if response.status_code == 200:
                print("✅ Telegram message sent")
            else:
                print(f"❌ Telegram send failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Telegram error: {e}")

    def process_command(self, message: str) -> Optional[str]:
        """Process Telegram command."""
        parts = message.strip().split()
        if not parts:
            return None

        command = parts[0].lower()

        if command == "/help" or command == "/start":
            return """
🤖 <b>한국 주식 돌파 탐지 봇</b>

<b>스캔:</b>
/scan - 전체 종목 스캔

<b>포지션 관리:</b>
/positions - 보유 포지션 보기
/close [종목코드] - 수동 청산
  예) /close 005930

<b>감시 목록:</b>
/add [종목코드] - 종목 추가
  예) /add 005930
/remove [종목코드] - 종목 제거
  예) /remove 005930
/list - 감시 종목 목록

<b>기타:</b>
/status - 시장 상태 확인
/stats - 거래 통계 (DB 모드)
/help - 도움말

<b>탐지 조건:</b>
📈 20일 고점 돌파
📊 거래량 50%+ 급증
🎯 돌파율 0~5% 이내
"""

        elif command == "/add":
            if len(parts) < 2:
                return "❌ 사용법: /add [종목코드]\n예) /add 005930"
            return self.add_stock(parts[1])

        elif command == "/remove":
            if len(parts) < 2:
                return "❌ 사용법: /remove [종목코드]\n예) /remove 005930"
            return self.remove_stock(parts[1])

        elif command == "/list":
            return self.list_watchlist()

        elif command == "/status":
            return self.get_market_status()

        elif command == "/scan":
            return "SCAN"

        elif command == "/positions":
            return self.list_positions()

        elif command == "/stats":
            return self.get_trade_stats()

        elif command == "/close":
            if len(parts) < 2:
                return "❌ 사용법: /close [종목코드]\n예) /close 005930"

            ticker = parts[1].strip()
            with self.positions_lock:
                held = any(p["ticker"] == ticker for p in self.positions)
            if not held:
                return f"❌ 포지션 없음: {ticker}"

            try:
                df = self.get_stock_data(ticker, days=7)

                if df is not None and len(df) > 0:
                    current_price = df["Close"].iloc[-1]
                    # close_position re-checks under the lock: if a scan closed
                    # it while we fetched the price, this returns False
                    if self.close_position(ticker, current_price, "수동 청산"):
                        return f"✅ {ticker} 포지션 청산됨"
                    return f"❌ {ticker} 포지션 청산 실패 (이미 청산되었거나 저장 오류)"
                else:
                    return f"❌ {ticker} 현재가 조회 실패"
            except Exception as e:
                return f"❌ 포지션 청산 오류: {e}"

        return None

    def _execute_scan_in_thread(self):
        """Execute scan in separate thread."""
        if self.is_scanning:
            self.send_telegram_message(
                "⚠️  이미 스캔이 진행 중입니다. 완료될 때까지 기다려주세요."
            )
            return

        if not self.scan_lock.acquire(blocking=False):
            self.send_telegram_message(
                "⚠️  다른 스캔이 진행 중입니다. 잠시 후 다시 시도해주세요."
            )
            return

        try:
            self.is_scanning = True
            print("\n🔔 Scan command received - starting scan")
            self.send_telegram_message("🇰🇷 스캔 시작...")
            self.run_scan(manual=True)
        except Exception as e:
            print(f"❌ Scan error: {e}")
            self.send_telegram_message(f"❌ 스캔 오류: {str(e)}")
        finally:
            self.is_scanning = False
            self.scan_lock.release()

    def check_telegram_updates(self):
        """Check for Telegram updates and process commands."""
        try:
            url = f"{self.base_url}/getUpdates"
            params = {"offset": self.last_update_id + 1, "timeout": 10}
            response = requests.get(url, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                if data.get("ok") and data.get("result"):
                    for update in data["result"]:
                        self.last_update_id = update["update_id"]

                        if "message" in update and "text" in update["message"]:
                            message_text = update["message"]["text"]
                            chat_id = str(update["message"]["chat"]["id"])

                            if chat_id == str(self.chat_id):
                                reply = self.process_command(message_text)

                                if reply == "SCAN":
                                    scan_thread = threading.Thread(
                                        target=self._execute_scan_in_thread,
                                        daemon=True,
                                    )
                                    scan_thread.start()

                                elif reply:
                                    self.send_telegram_message(reply)
        except Exception as e:
            print(f"⚠️  Telegram update error: {e}")

    def start_command_listener(self):
        """Start background Telegram command listener."""

        def listener_loop():
            while True:
                try:
                    self.check_telegram_updates()
                    time.sleep(2)
                except Exception as e:
                    print(f"⚠️  Listener error: {e}")
                    time.sleep(5)

        thread = threading.Thread(target=listener_loop, daemon=True)
        thread.start()
        print("✅ Telegram command listener started")

    # ========================================
    # Stock Data & Pattern Detection
    # ========================================

    def lookup_stock_name(self, ticker: str) -> Optional[str]:
        """Get stock name, or None if the ticker is unknown.

        pykrx returns an empty DataFrame (not an exception) for unknown tickers.
        """
        try:
            name = stock.get_market_ticker_name(ticker)
        except Exception:
            return None
        return name if isinstance(name, str) and name else None

    def get_stock_name(self, ticker: str) -> str:
        """Get stock name, falling back to the ticker."""
        return self.lookup_stock_name(ticker) or ticker

    def format_stock(self, ticker: str) -> str:
        """Format as "name(ticker)", or just the ticker if the name is unknown."""
        name = self.lookup_stock_name(ticker)
        return f"{name}({ticker})" if name else ticker

    def get_stock_data(self, ticker: str, days: int = 120) -> Optional[pd.DataFrame]:
        """Get stock data from pykrx."""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            df = stock.get_market_ohlcv_by_date(
                start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"), ticker
            )

            if df.empty:
                return None

            column_mapping = {
                "시가": "Open",
                "고가": "High",
                "저가": "Low",
                "종가": "Close",
                "거래량": "Volume",
            }

            df = df.rename(columns=column_mapping)
            required_columns = ["Open", "High", "Low", "Close", "Volume"]
            df = df[required_columns]

            return df
        except Exception as e:
            print(f"❌ {ticker} data query failed: {e}")
            return None

    def detect_pivot_breakout(self, df: pd.DataFrame, ticker: str) -> Optional[Dict]:
        """Detect pivot point breakout."""
        if df is None or len(df) < 30:
            return None

        try:
            recent = df.tail(30).copy()
            avg_volume = recent["Volume"].iloc[:-1].mean()
            current_volume = recent["Volume"].iloc[-1]
            volume_surge = (current_volume / avg_volume - 1) * 100

            close = recent["Close"].values
            current_price = close[-1]
            resistance = np.max(close[-20:-1])

            breakout = current_price > resistance
            breakout_pct = ((current_price - resistance) / resistance) * 100

            if breakout and volume_surge >= settings.VOLUME_SURGE_MIN and 0 < breakout_pct <= settings.BREAKOUT_MAX:
                signal = {
                    "ticker": ticker,
                    "name": self.get_stock_name(ticker),
                    "pattern": "피벗 돌파",
                    "resistance": resistance,
                    "current_price": current_price,
                    "breakout_pct": round(breakout_pct, 2),
                    "volume_surge": round(volume_surge, 2),
                }
                return signal
        except Exception:
            pass

        return None

    def analyze_stock(self, ticker: str) -> Optional[Dict]:
        """Analyze stock for breakout signal."""
        df = self.get_stock_data(ticker)
        if df is None:
            return None

        return self.detect_pivot_breakout(df, ticker)

    # ========================================
    # Message Formatting
    # ========================================

    def format_signal_message(self, signal: Dict) -> str:
        """Format signal as Telegram message."""
        ticker = signal["ticker"]
        name = signal.get("name", ticker)

        msg = f"""
🇰🇷 <b>[피벗 돌파 신호!]</b>

🏢 종목: <b>{name} ({ticker})</b>
💰 현재가: {signal['current_price']:,.0f}원
🎯 저항선: {signal['resistance']:,.0f}원
📈 돌파율: {signal['breakout_pct']}%

📊 거래량 급증: +{signal['volume_surge']}%

✅ 매수 신호!
⛔ 손절: 진입가 -7~8%

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return msg

    # ========================================
    # Scanning
    # ========================================

    def run_scan(self, manual: bool = False) -> List[Dict]:
        """Run scan on watchlist.

        Args:
            manual: If True, always send completion message. If False, only send when signals found.
        """
        print(f"\n{'=' * 60}")
        print("🔍 스캔 시작")
        print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🇰🇷 감시 종목: {len(self.watchlist)}개")
        print(f"{'=' * 60}\n")

        # 보유 포지션을 모르면 중복 신호를 막을 수 없으므로 스캔 중단
        if not self.check_positions():
            print("⛔ 포지션 조회 실패 - 스캔 중단\n")
            if manual:
                self.send_telegram_message(
                    "❌ 포지션 조회에 실패해 스캔을 중단했습니다. 잠시 후 다시 시도해주세요."
                )
            return []

        all_signals = []

        if self.watchlist:
            print("🇰🇷 종목 스캔 중...\n")
            for ticker in self.watchlist:
                try:
                    name = self.get_stock_name(ticker)
                    print(f"  🔍 {name}({ticker})...", end=" ")

                    # 이미 포지션이 있으면 스킵
                    if any(p["ticker"] == ticker for p in self.positions):
                        print("📌 보유중")
                        continue

                    signal = self.analyze_stock(ticker)
                    if signal:
                        # 먼저 포지션 저장 시도
                        saved = self.add_position(
                            ticker=ticker,
                            entry_price=signal["current_price"],
                            pattern=signal["pattern"],
                            signal=signal,
                        )
                        if saved:
                            # 저장 성공 시에만 텔레그램 알림 전송
                            all_signals.append(signal)
                            msg = self.format_signal_message(signal)
                            self.send_telegram_message(msg)
                            print("✅ 신호 발생!")
                        else:
                            print("⚠️ 포지션 저장 실패 (알림 생략)")
                        time.sleep(2)
                    else:
                        print("⚪")
                except Exception as e:
                    print(f"❌ Error: {e}")
            print()

        if all_signals:
            print(f"📊 {len(all_signals)}개 신호 발견")
        else:
            print("⚪ 신호 없음")

        print(f"\n{'=' * 60}\n")

        scan_time_str = datetime.now().strftime("%H:%M:%S")

        # 수동 스캔이거나 신호가 있을 때만 완료 메시지 전송
        if manual or all_signals:
            if all_signals:
                summary_msg = f"✅ [스캔 완료] {len(all_signals)}개 매수 신호 발견!"
            else:
                summary_msg = "⚪ [스캔 완료] 새로운 매수 신호 없음"

            self.send_telegram_message(f"{summary_msg}\n⏰ ({scan_time_str})")

        return all_signals

    def run_scheduled_scan(self) -> List[Dict]:
        """Run scheduled scan based on market hours.

        Holds scan_lock like manual scans, so a /scan during a scheduled scan
        (or vice versa) cannot produce duplicate signals or closes.
        """
        if not self.scan_lock.acquire(blocking=False):
            print("\n⏸️  Manual scan in progress. Skipping this cycle...\n")
            return []

        try:
            self.is_scanning = True

            if not self.is_market_open():
                print("\n⏸️  Market closed. Waiting for next session...")
                self.check_positions()
                return []

            return self.run_scan()
        finally:
            self.is_scanning = False
            self.scan_lock.release()

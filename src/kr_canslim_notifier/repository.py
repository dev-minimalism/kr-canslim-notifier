"""Repository classes for database operations."""

import json
from datetime import datetime
from typing import Dict, List, Optional

from .database import get_db


class PositionRepository:
    """Repository for position management in PostgreSQL."""

    def __init__(self):
        self.db = get_db()

    def get_all_open(self) -> List[Dict]:
        """Get all open positions."""
        query = """
            SELECT id, ticker, entry_price, entry_date, pattern,
                   stop_loss, take_profit, signal_data, status
            FROM positions
            WHERE status = 'open'
            ORDER BY entry_date DESC
        """
        rows = self.db.execute(query)
        return [self._row_to_dict(row) for row in rows]

    def get_by_ticker(self, ticker: str) -> Optional[Dict]:
        """Get open position by ticker."""
        query = """
            SELECT id, ticker, entry_price, entry_date, pattern,
                   stop_loss, take_profit, signal_data, status
            FROM positions
            WHERE ticker = %s AND status = 'open'
            LIMIT 1
        """
        row = self.db.execute_one(query, (ticker,))
        return self._row_to_dict(row) if row else None

    def exists(self, ticker: str) -> bool:
        """Check if open position exists for ticker."""
        query = """
            SELECT 1 FROM positions
            WHERE ticker = %s AND status = 'open'
            LIMIT 1
        """
        result = self.db.execute_one(query, (ticker,))
        return result is not None

    def add(
        self,
        ticker: str,
        entry_price: float,
        pattern: str,
        signal: Dict,
        stop_loss_pct: float = 0.08,
        take_profit_pct: float = 0.20,
    ) -> int:
        """
        Add new position.

        Args:
            ticker: Stock ticker code.
            entry_price: Entry price.
            pattern: Pattern name that triggered the signal.
            signal: Signal data dictionary.
            stop_loss_pct: Stop loss percentage (default 8%).
            take_profit_pct: Take profit percentage (default 20%).

        Returns:
            New position ID.
        """
        stop_loss = entry_price * (1 - stop_loss_pct)
        take_profit = entry_price * (1 + take_profit_pct)

        query = """
            INSERT INTO positions
            (ticker, entry_price, pattern, stop_loss, take_profit, signal_data, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'open')
            RETURNING id
        """
        result = self.db.execute_one(
            query,
            (ticker, entry_price, pattern, stop_loss, take_profit, json.dumps(signal)),
        )
        position_id = result["id"]
        print(f"  📝 Position added (DB): {ticker} @ {entry_price:,} [ID: {position_id}]")
        return position_id

    def close(
        self,
        ticker: str,
        exit_price: float,
        reason: str,
    ) -> Optional[Dict]:
        """
        Close position and move to trade history.

        Args:
            ticker: Stock ticker code.
            exit_price: Exit price.
            reason: Exit reason.

        Returns:
            Closed position info or None if not found.
        """
        # Get current position
        position = self.get_by_ticker(ticker)
        if not position:
            return None

        entry_price = float(position["entry_price"])
        entry_date = position["entry_date"]
        profit_pct = ((exit_price - entry_price) / entry_price) * 100
        holding_days = (datetime.now() - entry_date).days

        # Update position to closed (only if still open)
        update_query = """
            UPDATE positions
            SET status = 'closed',
                exit_price = %s,
                exit_date = NOW(),
                exit_reason = %s,
                profit_pct = %s,
                updated_at = NOW()
            WHERE id = %s AND status = 'open'
            RETURNING id
        """

        # Insert into trade history
        history_query = """
            INSERT INTO trade_history
            (position_id, ticker, entry_price, entry_date, exit_price, exit_date,
             exit_reason, profit_pct, holding_days, pattern)
            VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s)
        """

        # One transaction. If another connection closed the position after our
        # SELECT, the status guard matches no row and we record nothing.
        with self.db.get_cursor() as cursor:
            cursor.execute(
                update_query, (exit_price, reason, profit_pct, position["id"])
            )
            if cursor.fetchone() is None:
                return None
            cursor.execute(
                history_query,
                (
                    position["id"],
                    ticker,
                    entry_price,
                    entry_date,
                    exit_price,
                    reason,
                    profit_pct,
                    holding_days,
                    position.get("pattern"),
                ),
            )

        print(f"  ❌ Position closed (DB): {ticker} ({reason}) {profit_pct:+.2f}%")

        return {
            "ticker": ticker,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_date": entry_date,
            "profit_pct": profit_pct,
            "holding_days": holding_days,
            "reason": reason,
            "pattern": position.get("pattern"),
        }

    def get_trade_history(self, limit: int = 50) -> List[Dict]:
        """Get trade history (closed positions)."""
        query = """
            SELECT ticker, entry_price, entry_date, exit_price, exit_date,
                   exit_reason, profit_pct, holding_days, pattern
            FROM trade_history
            ORDER BY exit_date DESC
            LIMIT %s
        """
        return self.db.execute(query, (limit,))

    def get_stats(self) -> Dict:
        """Get trading statistics."""
        query = """
            SELECT
                COUNT(*) as total_trades,
                COUNT(CASE WHEN profit_pct > 0 THEN 1 END) as winning_trades,
                COUNT(CASE WHEN profit_pct <= 0 THEN 1 END) as losing_trades,
                COALESCE(AVG(profit_pct), 0) as avg_profit_pct,
                COALESCE(SUM(profit_pct), 0) as total_profit_pct,
                COALESCE(MAX(profit_pct), 0) as max_profit_pct,
                COALESCE(MIN(profit_pct), 0) as max_loss_pct,
                COALESCE(AVG(holding_days), 0) as avg_holding_days
            FROM trade_history
        """
        result = self.db.execute_one(query)
        if result:
            total = result["total_trades"]
            winning = result["winning_trades"]
            win_rate = (winning / total * 100) if total > 0 else 0
            return {
                "total_trades": total,
                "winning_trades": winning,
                "losing_trades": result["losing_trades"],
                "win_rate": win_rate,
                "avg_profit_pct": float(result["avg_profit_pct"]),
                "total_profit_pct": float(result["total_profit_pct"]),
                "max_profit_pct": float(result["max_profit_pct"]),
                "max_loss_pct": float(result["max_loss_pct"]),
                "avg_holding_days": float(result["avg_holding_days"]),
            }
        return {}

    def _row_to_dict(self, row: dict) -> Dict:
        """Convert database row to position dictionary."""
        if not row:
            return {}

        result = dict(row)

        # Parse signal_data JSON if exists
        if "signal_data" in result and result["signal_data"]:
            if isinstance(result["signal_data"], str):
                result["signal"] = json.loads(result["signal_data"])
            else:
                result["signal"] = result["signal_data"]
            del result["signal_data"]

        # Convert Decimal to float
        for key in ["entry_price", "stop_loss", "take_profit", "exit_price", "profit_pct"]:
            if key in result and result[key] is not None:
                result[key] = float(result[key])

        return result


class WatchlistRepository:
    """Repository for watchlist management in PostgreSQL."""

    def __init__(self):
        self.db = get_db()

    def get_all(self) -> List[str]:
        """Get all tickers in watchlist."""
        query = "SELECT ticker FROM watchlist ORDER BY added_at"
        rows = self.db.execute(query)
        return [row["ticker"] for row in rows]

    def add(self, ticker: str, name: str = None) -> bool:
        """Add ticker to watchlist."""
        query = """
            INSERT INTO watchlist (ticker, name)
            VALUES (%s, %s)
            ON CONFLICT (ticker) DO NOTHING
            RETURNING id
        """
        result = self.db.execute_one(query, (ticker, name))
        return result is not None

    def remove(self, ticker: str) -> bool:
        """Remove ticker from watchlist."""
        query = "DELETE FROM watchlist WHERE ticker = %s RETURNING id"
        result = self.db.execute_one(query, (ticker,))
        return result is not None

    def exists(self, ticker: str) -> bool:
        """Check if ticker exists in watchlist."""
        query = "SELECT 1 FROM watchlist WHERE ticker = %s LIMIT 1"
        result = self.db.execute_one(query, (ticker,))
        return result is not None

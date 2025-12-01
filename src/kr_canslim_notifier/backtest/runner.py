"""
Korean Stock Pivot Breakout Strategy Backtester

Features:
- Pivot point breakout detection
- Volume surge confirmation
- Stop-loss / Take-profit / Time exit
- CAGR (Compound Annual Growth Rate) report
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from pykrx import stock

from .config import BacktestConfig, default_config


class PivotBreakoutBacktester:
    """Korean stock pivot breakout strategy backtester."""

    def __init__(self, config: Optional[BacktestConfig] = None):
        """Initialize backtester with configuration."""
        self.config = config or default_config
        self.price_data: Dict[str, pd.DataFrame] = {}
        self.trades_log: List[Dict] = []
        self.open_positions: Dict[str, Dict] = {}
        self.capital = self.config.initial_capital
        self.position_size = self.config.initial_capital * self.config.position_size_pct

        print("📈 피벗 돌파 백테스터 초기화")
        print(f"   - 기간: {self.config.start_date} ~ {self.config.end_date}")
        print(f"   - 초기 자본: {self.config.initial_capital:,.0f}원")
        print(f"   - 포지션 크기: {self.position_size:,.0f}원")
        print("-" * 50)

    def get_stock_name(self, ticker: str) -> str:
        """Get stock name from ticker."""
        try:
            name = stock.get_market_ticker_name(ticker)
            return name if name else ticker
        except Exception:
            return ticker

    def load_all_data(self, tickers: List[str]) -> bool:
        """Load price data for all tickers."""
        print(f"⏳ 데이터 로딩 중 ({len(tickers)}개 종목)...")

        # Load extra data for lookback period
        start_dt = datetime.strptime(self.config.start_date, "%Y-%m-%d")
        load_start = (start_dt - timedelta(days=self.config.lookback_period * 2)).strftime("%Y%m%d")
        load_end = datetime.strptime(self.config.end_date, "%Y-%m-%d").strftime("%Y%m%d")

        loaded = 0
        for ticker in tickers:
            try:
                df = stock.get_market_ohlcv_by_date(load_start, load_end, ticker)

                if df.empty:
                    print(f"   ⚠️ {ticker} 데이터 없음")
                    continue

                # Rename columns
                df = df.rename(columns={
                    "시가": "Open",
                    "고가": "High",
                    "저가": "Low",
                    "종가": "Close",
                    "거래량": "Volume",
                })
                df = df[["Open", "High", "Low", "Close", "Volume"]]

                # Calculate indicators
                df["Avg_Volume"] = df["Volume"].rolling(window=self.config.lookback_period).mean()
                df["Pivot_Resist"] = (
                    df["High"].shift(1).rolling(window=self.config.lookback_period).max()
                )

                self.price_data[ticker] = df.dropna()
                loaded += 1

            except Exception as e:
                print(f"   ❌ {ticker} 로딩 실패: {e}")

        print(f"✅ 데이터 로딩 완료: {loaded}/{len(tickers)}개")
        print("-" * 50)
        return loaded > 0

    def check_entry_signal(self, ticker: str, date) -> Optional[Dict]:
        """Check pivot breakout entry signal."""
        try:
            data = self.price_data[ticker].loc[date]
        except KeyError:
            return None

        resistance = data["Pivot_Resist"]
        current_close = data["Close"]
        current_volume = data["Volume"]
        avg_volume = data["Avg_Volume"]

        # Volume surge check
        if avg_volume <= 0:
            return None
        volume_surge = ((current_volume - avg_volume) / avg_volume) * 100
        pass_volume = volume_surge >= self.config.volume_surge_pct

        # Breakout check
        breakout_pct = ((current_close - resistance) / resistance) * 100
        pass_breakout = (current_close > resistance) and (0 < breakout_pct <= self.config.breakout_pct_max)

        if pass_volume and pass_breakout:
            return {
                "entry_price": current_close,
                "signal_type": "피벗 돌파",
                "volume_surge": volume_surge,
                "breakout_pct": breakout_pct,
            }

        return None

    def open_position(self, ticker: str, date, signal: Dict):
        """Open new position."""
        entry_price = signal["entry_price"]
        name = self.get_stock_name(ticker)

        self.open_positions[ticker] = {
            "entry_date": date,
            "entry_price": entry_price,
            "stop_loss": entry_price * (1 - self.config.stop_loss_pct),
            "take_profit": entry_price * (1 + self.config.take_profit_pct),
            "holding_days_max": date + timedelta(days=self.config.holding_days_max),
        }

        print(f"  📈 [매수] {date.date()} | {name}({ticker}) | {entry_price:,.0f}원")

    def close_position(self, ticker: str, date, exit_price: float, reason: str):
        """Close position."""
        pos = self.open_positions.pop(ticker)
        entry_price = pos["entry_price"]
        name = self.get_stock_name(ticker)

        profit_pct = (exit_price - entry_price) / entry_price
        profit_amt = self.position_size * profit_pct

        self.capital += profit_amt

        self.trades_log.append({
            "ticker": ticker,
            "name": name,
            "entry_date": pos["entry_date"].date(),
            "exit_date": date.date(),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "profit_pct": profit_pct * 100,
            "profit_amt": profit_amt,
            "reason": reason,
        })

        icon = "✅" if profit_pct > 0 else "🔻"
        print(f"  {icon} [매도] {date.date()} | {name}({ticker}) | {reason} | {profit_pct * 100:+.2f}%")

    def run_simulation(self):
        """Run main simulation loop."""
        if not self.price_data:
            print("❌ 시뮬레이션할 데이터 없음")
            return

        # Get trading dates from first ticker
        first_ticker = list(self.price_data.keys())[0]
        start_dt = datetime.strptime(self.config.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(self.config.end_date, "%Y-%m-%d")

        all_dates = self.price_data[first_ticker].index
        trading_dates = all_dates[(all_dates >= start_dt) & (all_dates <= end_dt)]

        if trading_dates.empty:
            print("❌ 시뮬레이션 기간에 거래일 없음")
            return

        print(f"\n🚀 시뮬레이션 시작 ({len(trading_dates)} 거래일)...")

        start_time = time.time()

        for date in trading_dates:
            # 1. Check position exits
            for ticker in list(self.open_positions.keys()):
                pos = self.open_positions[ticker]

                try:
                    today_data = self.price_data[ticker].loc[date]
                except KeyError:
                    continue

                if today_data["Low"] <= pos["stop_loss"]:
                    self.close_position(ticker, date, pos["stop_loss"], "손절")
                elif today_data["High"] >= pos["take_profit"]:
                    self.close_position(ticker, date, pos["take_profit"], "익절")
                elif date > pos["holding_days_max"]:
                    self.close_position(ticker, date, today_data["Close"], "기간만료")

            # 2. Check new entries
            for ticker in self.price_data.keys():
                if ticker in self.open_positions:
                    continue

                signal = self.check_entry_signal(ticker, date)
                if signal:
                    self.open_position(ticker, date, signal)

        end_time = time.time()
        print(f"\n✅ 시뮬레이션 완료! (소요시간: {end_time - start_time:.2f}초)")
        print("-" * 50)

    def print_report(self):
        """Print backtest results report."""
        if not self.trades_log:
            print("📊 결과: 거래 없음")
            return

        report_df = pd.DataFrame(self.trades_log)

        total_trades = len(report_df)
        wins = report_df[report_df["profit_pct"] > 0]
        losses = report_df[report_df["profit_pct"] <= 0]

        win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0

        avg_profit = wins["profit_pct"].mean() if len(wins) > 0 else 0
        avg_loss = losses["profit_pct"].mean() if len(losses) > 0 else 0

        if len(losses) == 0 or losses["profit_pct"].sum() == 0:
            profit_factor = float("inf") if wins["profit_pct"].sum() > 0 else 1.0
        else:
            profit_factor = wins["profit_pct"].sum() / abs(losses["profit_pct"].sum())

        total_pnl_amt = report_df["profit_amt"].sum()
        final_capital = self.config.initial_capital + total_pnl_amt
        total_return_pct = (total_pnl_amt / self.config.initial_capital) * 100

        # CAGR calculation
        start_dt = datetime.strptime(self.config.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(self.config.end_date, "%Y-%m-%d")
        total_days = (end_dt - start_dt).days

        cagr = 0.0
        if total_days > 0:
            num_years = total_days / 365.25
            total_return_mult = final_capital / self.config.initial_capital
            if total_return_mult > 0:
                cagr = ((total_return_mult ** (1 / num_years)) - 1) * 100

        print("\n" + "=" * 50)
        print("📊 백테스트 결과")
        print("=" * 50)
        print(f"  기간: {self.config.start_date} ~ {self.config.end_date} ({total_days}일)")
        print(f"  초기 자본: {self.config.initial_capital:,.0f}원")
        print(f"  최종 자본: {final_capital:,.0f}원")
        print("-" * 50)
        print("성과 요약:")
        print(f"  총 수익률: {total_return_pct:+.2f}%")
        print(f"  CAGR: {cagr:+.2f}%")
        print(f"  총 거래: {total_trades}회")
        print(f"  승률: {win_rate:.1f}% ({len(wins)}승 / {len(losses)}패)")
        print(f"  평균 수익: {avg_profit:+.2f}%")
        print(f"  평균 손실: {avg_loss:.2f}%")
        print(f"  Profit Factor: {profit_factor:.2f}")
        print("-" * 50)

        # Summary by ticker
        print("종목별 성과:")
        ticker_summary = report_df.groupby("ticker").agg({
            "name": "first",
            "profit_pct": ["count", "sum", "mean"],
        }).round(2)
        ticker_summary.columns = ["종목명", "거래수", "총수익률", "평균수익률"]
        ticker_summary = ticker_summary.sort_values("총수익률", ascending=False)
        print(ticker_summary.to_string())

        print("-" * 50)
        print("최근 거래 (10건):")
        recent = report_df[["name", "entry_date", "exit_date", "profit_pct", "reason"]].tail(10)
        recent.columns = ["종목", "진입일", "청산일", "수익률%", "사유"]
        print(recent.to_string(index=False))
        print("=" * 50)


def run_backtest(config: Optional[BacktestConfig] = None):
    """Convenience function to run backtest."""
    bt = PivotBreakoutBacktester(config)

    # 1. Load data
    if not bt.load_all_data(bt.config.tickers):
        print("❌ 데이터 로딩 실패")
        return

    # 2. Run simulation
    bt.run_simulation()

    # 3. Print report
    bt.print_report()

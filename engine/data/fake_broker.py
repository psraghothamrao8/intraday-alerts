"""
FakeBroker implementation for testing, replay, and backtesting.
Reads from Parquet candles and drives simulated ticks.
Implements spec 05 §5.
"""
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Dict, List, Optional
import pandas as pd
from engine.core.clock import get_clock, IST
from engine.data.broker_base import Broker, Quote, Tick


class FakeBroker:
    """Simulated broker that replays recorded 1-minute Parquet candle data."""

    def __init__(
        self,
        candles_dir: Path | str = "data/candles/1m",
        candles_df: Optional[pd.DataFrame] = None
    ):
        self.name = "fake"
        self.candles_dir = Path(candles_dir)
        self.candles_df = candles_df
        self._subscribers: Dict[str, List[Callable[[Tick], None]]] = {}

    async def login(self) -> None:
        pass

    async def instruments(self) -> pd.DataFrame:
        symbols = []
        if self.candles_df is not None and not self.candles_df.empty:
            symbols = self.candles_df["symbol"].unique().tolist()
        return pd.DataFrame({
            "symbol": symbols,
            "token": [str(i) for i in range(len(symbols))],
            "exchange": ["NSE"] * len(symbols),
            "series": ["EQ"] * len(symbols),
            "isin": [f"INE{s}" for s in symbols],
            "tick_size": [0.05] * len(symbols),
        })

    async def quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        quotes_dict = {}
        now_dt = get_clock().now()

        for sym in symbols:
            df = await self.intraday_candles(sym, day=now_dt.date())
            if df.empty:
                # Default mock quote
                quotes_dict[sym] = Quote(
                    symbol=sym, ltp=100.0, volume=1000,
                    open=100.0, high=102.0, low=99.0, prev_close=100.0,
                    upper_circuit=110.0, lower_circuit=90.0, ts=now_dt
                )
            else:
                last_row = df.iloc[-1]
                quotes_dict[sym] = Quote(
                    symbol=sym,
                    ltp=float(last_row["close"]),
                    volume=int(df["volume"].sum()),
                    open=float(df.iloc[0]["open"]),
                    high=float(df["high"].max()),
                    low=float(df["low"].min()),
                    prev_close=float(df.iloc[0]["open"]),
                    upper_circuit=float(df.iloc[0]["open"]) * 1.10,
                    lower_circuit=float(df.iloc[0]["open"]) * 0.90,
                    ts=now_dt
                )
        return quotes_dict

    async def intraday_candles(
        self,
        symbol: str,
        interval: str = "1minute",
        day: Optional[date] = None
    ) -> pd.DataFrame:
        if self.candles_df is not None:
            df = self.candles_df[self.candles_df["symbol"] == symbol].copy()
            if day:
                df = df[pd.to_datetime(df["ts"]).dt.date == day]
            return df.sort_values("ts")

        if day:
            file_path = self.candles_dir / f"{day.isoformat()}.parquet"
            if file_path.exists():
                full_df = pd.read_parquet(file_path)
                sym_df = full_df[full_df["symbol"] == symbol].copy()
                return sym_df.sort_values("ts")

        return pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume"])

    async def daily_candles(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    async def subscribe(self, symbols: List[str], on_tick: Callable[[Tick], None]) -> None:
        for s in symbols:
            if s not in self._subscribers:
                self._subscribers[s] = []
            self._subscribers[s].append(on_tick)

    async def unsubscribe(self, symbols: List[str]) -> None:
        for s in symbols:
            self._subscribers.pop(s, None)

    async def mis_short_lists(self) -> Optional[pd.DataFrame]:
        return None

    def push_tick(self, tick: Tick) -> None:
        """Helper for test runners to dispatch a tick to active subscribers."""
        for callback in self._subscribers.get(tick.symbol, []):
            callback(tick)

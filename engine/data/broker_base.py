"""
Broker protocol and core market data data structures.
Implements spec 05 §5.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Protocol
import pandas as pd


@dataclass
class Quote:
    symbol: str
    ltp: float
    volume: int  # today's cumulative volume
    open: float
    high: float
    low: float
    prev_close: float
    upper_circuit: Optional[float] = None
    lower_circuit: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    ts: Optional[datetime] = None


@dataclass
class Tick:
    symbol: str
    ltp: float
    cum_volume: int
    ts: datetime


class Broker(Protocol):
    """Abstract broker interface required by the trading engine."""
    name: str

    async def login(self) -> None:
        ...

    async def instruments(self) -> pd.DataFrame:
        """DataFrame with columns: symbol, token, exchange, series, isin, tick_size."""
        ...

    async def quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """Fetch quotes for a list of symbols (batches internally if needed)."""
        ...

    async def intraday_candles(
        self,
        symbol: str,
        interval: str = "1minute",
        day: Optional[date] = None
    ) -> pd.DataFrame:
        """DataFrame with columns: ts, open, high, low, close, volume."""
        ...

    async def daily_candles(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """DataFrame with columns: ts, open, high, low, close, volume."""
        ...

    async def subscribe(self, symbols: List[str], on_tick: Callable[[Tick], None]) -> None:
        """Subscribe to live market feed ticks."""
        ...

    async def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from live market feed ticks."""
        ...

    async def mis_short_lists(self) -> Optional[pd.DataFrame]:
        """DataFrame with columns: symbol, mis_allowed, short_allowed; or None to use local CSV."""
        ...

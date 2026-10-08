"""
Base strategy interface (spec 01 §6, spec 07 §4.1).
Every strategy implements this uniform interface so live and backtest share the same code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd

from engine.core.models import Candle, Signal, Tick


class Strategy(ABC):
    """Abstract base class for all alert strategies."""

    def __init__(self, name: str):
        self.name = name

    def on_start(self, universe_df: pd.DataFrame) -> None:
        """Called once when the engine starts for the trading day."""
        pass

    async def on_filing(self, filing: Dict[str, Any], current_price: Optional[float] = None, **kwargs) -> Optional[Signal]:
        """Called when a new exchange filing is received and parsed."""
        return None

    def on_candle_1m(self, candle: Candle) -> Optional[Signal]:
        """Called when a 1-minute candle completes (at MM:02)."""
        return None

    def on_candle_5m(self, candle: Candle) -> Optional[Signal]:
        """Called when a 5-minute candle completes (at MM:02)."""
        return None

    def on_tick(self, tick: Tick) -> Optional[Signal]:
        """Called on every live tick received from the broker feed."""
        return None

    def on_clock(self, now: datetime) -> Optional[List[Signal]]:
        """Called periodically on clock tick (e.g. 09:20 for ORB, 14:55 for S4)."""
        return None

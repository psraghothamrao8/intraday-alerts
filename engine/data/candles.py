"""
Candle aggregation and VWAP calculations.
Generates 1m and 5m OHLCV bars from ticks, handles missing minutes,
and calculates day VWAP and Anchored VWAP per spec 05 §7.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from engine.data.broker_base import Tick


@dataclass
class Candle:
    symbol: str
    ts: datetime  # Start time of candle (e.g. 09:15:00)
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_complete: bool = False

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def timestamp(self) -> datetime:
        return self.ts


class CandleManager:
    """Manages tick aggregation, missing minute interpolation, 5m bar rollup, and VWAP for a symbol."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.candles_1m: List[Candle] = []
        self.candles_5m: List[Candle] = []
        self._current_1m: Optional[Candle] = None
        self._last_cum_volume: Optional[int] = None
        self._last_close: Optional[float] = None

    def seed_from_df(self, df: pd.DataFrame) -> None:
        """Seed 1-minute candles from a DataFrame."""
        if df.empty:
            return
        self.candles_1m.clear()
        for _, row in df.iterrows():
            ts = pd.to_datetime(row["ts"]).to_pydatetime()
            c = Candle(
                symbol=self.symbol,
                ts=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                is_complete=True,
            )
            self.candles_1m.append(c)
            self._last_close = c.close

        self._rebuild_5m_candles()

    def on_tick(self, tick: Tick) -> Tuple[List[Candle], List[Candle]]:
        """
        Process an incoming tick.
        Returns: (newly_completed_1m_candles, newly_completed_5m_candles)
        """
        completed_1m: List[Candle] = []
        completed_5m: List[Candle] = []

        tick_min = tick.ts.replace(second=0, microsecond=0)

        # Compute incremental volume
        if self._last_cum_volume is None:
            vol_delta = tick.cum_volume
        else:
            vol_delta = max(0, tick.cum_volume - self._last_cum_volume)
        self._last_cum_volume = tick.cum_volume

        if self._current_1m is None:
            # First candle
            self._current_1m = Candle(
                symbol=self.symbol,
                ts=tick_min,
                open=tick.ltp,
                high=tick.ltp,
                low=tick.ltp,
                close=tick.ltp,
                volume=vol_delta,
                is_complete=False,
            )
            self._last_close = tick.ltp
            return completed_1m, completed_5m

        if tick_min == self._current_1m.ts:
            # Same minute: update high, low, close, volume
            self._current_1m.high = max(self._current_1m.high, tick.ltp)
            self._current_1m.low = min(self._current_1m.low, tick.ltp)
            self._current_1m.close = tick.ltp
            self._current_1m.volume += vol_delta
            self._last_close = tick.ltp
        else:
            # Minute has advanced!
            self._current_1m.is_complete = True
            completed_1m.append(self._current_1m)
            self.candles_1m.append(self._current_1m)
            self._last_close = self._current_1m.close

            # Check for missing minutes between previous minute and current tick_min
            prev_ts = self._current_1m.ts
            step_ts = prev_ts + timedelta(minutes=1)
            while step_ts < tick_min:
                # Interpolate missing minute copying previous close with 0 volume
                missing_candle = Candle(
                    symbol=self.symbol,
                    ts=step_ts,
                    open=self._last_close,
                    high=self._last_close,
                    low=self._last_close,
                    close=self._last_close,
                    volume=0,
                    is_complete=True,
                )
                completed_1m.append(missing_candle)
                self.candles_1m.append(missing_candle)
                step_ts += timedelta(minutes=1)

            # Start new 1-minute candle
            self._current_1m = Candle(
                symbol=self.symbol,
                ts=tick_min,
                open=tick.ltp,
                high=tick.ltp,
                low=tick.ltp,
                close=tick.ltp,
                volume=vol_delta,
                is_complete=False,
            )
            self._last_close = tick.ltp

            # Rebuild / check completed 5m candles
            completed_5m = self._update_5m_candles()

        return completed_1m, completed_5m

    def _update_5m_candles(self) -> List[Candle]:
        """Aggregate completed 1-minute candles into 5-minute candles aligned to 09:15."""
        new_completed_5m = []
        if len(self.candles_1m) < 5:
            return new_completed_5m

        # Group 1m candles by 5-minute bucket starting from 09:15
        buckets: Dict[datetime, List[Candle]] = {}
        for c in self.candles_1m:
            # Calculate alignment offset relative to 09:15
            m = c.ts.minute
            bucket_min = (m // 5) * 5
            bucket_ts = c.ts.replace(minute=bucket_min, second=0, microsecond=0)
            if bucket_ts not in buckets:
                buckets[bucket_ts] = []
            buckets[bucket_ts].append(c)

        for b_ts, c_list in sorted(buckets.items()):
            # A 5-minute candle is complete if it has 5 complete 1-minute bars
            # or if the current minute has advanced beyond b_ts + 5 min
            current_minute = self._current_1m.ts if self._current_1m else None
            is_done = len(c_list) == 5 or (current_minute and current_minute >= b_ts + timedelta(minutes=5))
            if is_done and not any(existing.ts == b_ts and existing.is_complete for existing in self.candles_5m):
                candle_5m = Candle(
                    symbol=self.symbol,
                    ts=b_ts,
                    open=c_list[0].open,
                    high=max(c.high for c in c_list),
                    low=min(c.low for c in c_list),
                    close=c_list[-1].close,
                    volume=sum(c.volume for c in c_list),
                    is_complete=True,
                )
                self.candles_5m.append(candle_5m)
                new_completed_5m.append(candle_5m)

        return new_completed_5m

    def _rebuild_5m_candles(self) -> None:
        self.candles_5m.clear()
        self._update_5m_candles()


def compute_vwap(candles_1m: List[Candle]) -> float:
    """
    Day VWAP = Σ(typical price × vol) ÷ Σ vol from 09:15.
    If total volume is 0, returns the last candle's close.
    """
    if not candles_1m:
        return 0.0

    total_pv = 0.0
    total_vol = 0
    for c in candles_1m:
        tp = (c.high + c.low + c.close) / 3.0
        total_pv += tp * c.volume
        total_vol += c.volume

    if total_vol == 0:
        return candles_1m[-1].close
    return total_pv / total_vol


def compute_anchored_vwap(candles_1m: List[Candle], anchor_time: datetime) -> float:
    """
    Anchored VWAP from the 1-minute bar that contains the anchor_time forward.
    """
    anchor_min = anchor_time.replace(second=0, microsecond=0)
    eligible = [c for c in candles_1m if c.ts >= anchor_min]
    return compute_vwap(eligible)


def is_candle_complete(candle_end_time: datetime, now_dt: datetime, grace_sec: int = 2) -> bool:
    """A candle is complete at its end time plus grace seconds (spec 05 §7)."""
    return now_dt >= (candle_end_time + timedelta(seconds=grace_sec))


class CandleAggregator:
    """Manages candles across multiple symbols, aggregating 1m to 5m and computing VWAP."""

    def __init__(self):
        self.managers: Dict[str, CandleManager] = {}

    def get_manager(self, symbol: str) -> CandleManager:
        if symbol not in self.managers:
            self.managers[symbol] = CandleManager(symbol)
        return self.managers[symbol]

    def on_tick(self, symbol: str, ts: datetime, ltp: float, volume: int = 0) -> List[Any]:
        mgr = self.get_manager(symbol)
        tick = Tick(symbol=symbol, ltp=ltp, cum_volume=volume, ts=ts)
        completed_1m, _ = mgr.on_tick(tick)
        return completed_1m

    def on_candle_1m(self, candle: Any) -> List[Any]:
        mgr = self.get_manager(candle.symbol)
        ts = candle.timestamp if hasattr(candle, "timestamp") else candle.ts
        c_local = Candle(
            symbol=candle.symbol,
            ts=ts,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            is_complete=True,
        )
        mgr.candles_1m.append(c_local)
        return mgr._update_5m_candles()

    def get_anchored_vwap(self, symbol: str, anchor_ts_str: str) -> Optional[float]:
        mgr = self.managers.get(symbol)
        if not mgr or not mgr.candles_1m:
            return None
        try:
            anchor_dt = datetime.fromisoformat(anchor_ts_str)
            return compute_anchored_vwap(mgr.candles_1m, anchor_dt)
        except Exception:
            return compute_vwap(mgr.candles_1m)

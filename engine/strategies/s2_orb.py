"""
Strategy S2: Stocks-in-play opening-range breakout (ORB) (spec 02 §S2).
Implements RVOL ranking at 09:20, setup classification, 1-minute close breakout,
extended-candle skips, daily cap, and ORB exits.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from engine.config import get_settings
from engine.core.clock import IST, get_clock
from engine.core.exits import compute_orb_exits
from engine.core.models import Candle, Signal, Tick
from engine.core.risk import round_tick
from engine.strategies.base import Strategy

logger = logging.getLogger("engine.strategies.s2_orb")


@dataclass
class OrbSetup:
    symbol: str
    side: str                            # "LONG" or "SHORT"
    trigger: float                       # High for LONG, Low for SHORT
    or_open: float
    or_high: float
    or_low: float
    or_close: float
    or_volume: int
    rvol: float
    rvol_rank: int
    atr14: float
    gap_pct: float
    has_catalyst: bool
    strength: int


class S2OrbStrategy(Strategy):
    """S2 Strategy: Opening-Range Breakout (ORB)."""

    def __init__(self):
        super().__init__("S2")
        self.settings = get_settings()
        self.cfg = self.settings.strategies.s2_orb

        self.universe_map: Dict[str, dict] = {}
        self.eligible_symbols: Set[str] = set()
        self.catalyst_symbols: Set[str] = set()

        # State for trading day
        self.or_candles: Dict[str, Candle] = {}   # First 5-minute candle (09:15-09:20)
        self.setups: Dict[str, OrbSetup] = {}     # Ranked setups (top 20)
        self.triggered_symbols: Set[str] = set()
        self.daily_entries: int = 0
        self.ranking_done: bool = False

    def on_start(self, universe_df: pd.DataFrame) -> None:
        """Filter eligible symbols nightly and reset day state."""
        self.universe_map = {row["symbol"]: row.to_dict() for _, row in universe_df.iterrows()}
        self.eligible_symbols.clear()
        self.or_candles.clear()
        self.setups.clear()
        self.triggered_symbols.clear()
        self.daily_entries = 0
        self.ranking_done = False

        for sym, u in self.universe_map.items():
            if not u.get("mis_allowed", True):
                continue
            if u.get("series") != "EQ":
                continue
            if u.get("asm_stage", 0) >= 2 or u.get("gsm", False):
                continue

            adv = float(u.get("adv_cr", 0.0) or 0.0)
            prev_close = float(u.get("prev_close", 0.0) or 0.0)
            atr_pct = float(u.get("atr_pct", 0.0) or 0.0)

            if adv >= self.cfg.min_adv_cr and prev_close >= self.settings.universe.min_price_inr and atr_pct >= self.cfg.min_atr_pct:
                self.eligible_symbols.add(sym)

        logger.info(f"S2 ORB initialized with {len(self.eligible_symbols)} eligible symbols.")

    def set_catalyst_symbols(self, symbols: Set[str]) -> None:
        """Set symbols that had exchange filings since previous close."""
        self.catalyst_symbols = set(symbols)

    async def on_filing(self, filing: Dict[str, Any], current_price: Optional[float] = None, **kwargs) -> Optional[Signal]:
        """Track filings as catalysts for S2 stocks."""
        sym = filing.get("symbol")
        if sym:
            self.catalyst_symbols.add(sym)
        return None

    def on_candle_5m(self, candle: Candle) -> Optional[Signal]:
        """Collect the first 5-minute candle (09:15-09:20)."""
        sym = candle.symbol
        if sym not in self.eligible_symbols:
            return None

        # Check if this is the 09:15 candle (ending at 09:20)
        c_ts = getattr(candle, "timestamp", getattr(candle, "ts", None))
        c_time = c_ts.time() if c_ts else None
        if c_time and c_time.hour == 9 and c_time.minute in (15, 20):
            if sym not in self.or_candles:
                self.or_candles[sym] = candle

        return None

    def compute_ranking(self, nifty_5m_dir: Optional[str] = None) -> List[OrbSetup]:
        """
        Rank eligible symbols at 09:20:02 by RVOL and build top 20 setups.
        Per spec 02 §S2.2-S2.5.
        """
        candidates: List[dict] = []

        for sym, candle in self.or_candles.items():
            u = self.universe_map.get(sym, {})
            baseline_vol = float(u.get("or_vol_avg14", 0.0) or 0.0)
            if baseline_vol <= 0:
                # Fallback estimate per spec 05 §6: ~4% of day's volume in first 5 min
                adv = float(u.get("adv_cr", 0.0) or 0.0)
                prev_close = float(u.get("prev_close", 0.0) or 0.0)
                if adv > 0 and prev_close > 0:
                    baseline_vol = (adv * 1e7 / prev_close) * 0.04
                else:
                    continue

            if baseline_vol <= 0:
                continue

            rvol = candle.volume / baseline_vol
            if rvol < self.cfg.min_rvol:
                continue

            candidates.append({
                "symbol": sym,
                "candle": candle,
                "rvol": rvol,
                "universe": u,
            })

        # Rank by RVOL descending and take top N (default 20)
        candidates.sort(key=lambda x: x["rvol"], reverse=True)
        top_candidates = candidates[:self.cfg.top_n]

        ranked_setups: List[OrbSetup] = []

        for rank_idx, item in enumerate(top_candidates, 1):
            sym = item["symbol"]
            c = item["candle"]
            rvol = item["rvol"]
            u = item["universe"]
            atr14 = float(u.get("atr14", 5.0) or 5.0)
            prev_close = float(u.get("prev_close", 100.0) or 100.0)

            # Setup direction: C > O -> LONG, C < O -> SHORT
            if c.close > c.open:
                side = "LONG"
                trigger = c.high
            elif c.close < c.open:
                side = "SHORT"
                trigger = c.low
                # Verify shortability: F&O or band_room >= 10%
                is_fno = bool(u.get("fno", False))
                if not is_fno and not u.get("short_allowed", True):
                    continue
            else:
                continue  # C == O skip

            # Opening range width filter: (H - L) <= max_or_range_atr * ATR14 (0.6)
            or_range = c.high - c.low
            if or_range > self.cfg.max_or_range_atr * atr14:
                continue

            # Gap %
            gap_pct = ((c.open / prev_close) - 1.0) * 100.0
            has_catalyst = sym in self.catalyst_symbols

            # Provisional Strength (1-10) per spec 02 §S2.5:
            # Base 5. +1 if RVOL >= 3. +1 if RVOL rank <= 5. +1 if catalyst.
            # +1 if gap >= 1% in trade direction. +1 if Nifty points same way.
            # -1 if opening range > 0.4 * ATR14. Clamp 1-10.
            str_score = 5
            if rvol >= 3.0:
                str_score += 1
            if rank_idx <= 5:
                str_score += 1
            if has_catalyst:
                str_score += 1

            if side == "LONG" and gap_pct >= 1.0:
                str_score += 1
            elif side == "SHORT" and gap_pct <= -1.0:
                str_score += 1

            if nifty_5m_dir == side:
                str_score += 1

            if or_range > 0.4 * atr14:
                str_score -= 1

            strength = max(1, min(10, str_score))

            setup = OrbSetup(
                symbol=sym,
                side=side,
                trigger=trigger,
                or_open=c.open,
                or_high=c.high,
                or_low=c.low,
                or_close=c.close,
                or_volume=c.volume,
                rvol=rvol,
                rvol_rank=rank_idx,
                atr14=atr14,
                gap_pct=gap_pct,
                has_catalyst=has_catalyst,
                strength=strength,
            )
            ranked_setups.append(setup)
            self.setups[sym] = setup

        self.ranking_done = True
        logger.info(f"S2 ORB generated {len(ranked_setups)} ranked setups at 09:20.")
        return ranked_setups

    def on_clock(self, now: datetime) -> Optional[List[Signal]]:
        """Trigger RVOL ranking at 09:20."""
        if not self.ranking_done and now.time() >= time(9, 20):
            self.compute_ranking()
        return None

    def on_candle_1m(self, candle: Candle) -> Optional[Signal]:
        """
        Evaluate 1-minute close breakout against setup trigger (09:21 - 11:00).
        Per spec 02 §S2.4.
        """
        c_ts = getattr(candle, "timestamp", getattr(candle, "ts", None))
        c_time = c_ts.time() if c_ts else None
        if not c_time:
            return None

        if not self.ranking_done and c_time >= time(9, 21):
            self.compute_ranking()

        if not self.ranking_done:
            return None

        # Check 3-per-day cap
        if self.daily_entries >= self.cfg.max_trades_per_day:
            return None

        sym = candle.symbol
        if sym not in self.setups or sym in self.triggered_symbols:
            return None

        # Check time window: 09:21 to entry_until (default 11:00)
        entry_until_time = time(11, 0)
        if c_time < time(9, 21) or c_time > entry_until_time:
            return None

        setup = self.setups[sym]
        side = setup.side
        trigger = setup.trigger
        max_ext = self.cfg.max_extension_pct / 100.0  # 0.004

        # 1. Breakout check
        if side == "LONG":
            if candle.close <= trigger:
                return None
            # Extended-candle skip: close > trigger * (1 + 0.4%)
            if candle.close > trigger * (1.0 + max_ext):
                logger.info(f"S2 {sym} LONG breakout skipped: extended {candle.close:.2f} > {trigger * (1.0 + max_ext):.2f}")
                return None
            entry_price = round_tick(candle.close * (1.0 + self.cfg.entry_slip_pct / 100.0))
        else:  # SHORT
            if candle.close >= trigger:
                return None
            # Extended-candle skip: close < trigger * (1 - 0.4%)
            if candle.close < trigger * (1.0 - max_ext):
                logger.info(f"S2 {sym} SHORT breakout skipped: extended {candle.close:.2f} < {trigger * (1.0 - max_ext):.2f}")
                return None
            entry_price = round_tick(candle.close * (1.0 - self.cfg.entry_slip_pct / 100.0))

        # 2. Exits using ORB exit template (spec 03 §4.2)
        u = self.universe_map.get(sym, {})
        is_fno = bool(u.get("fno", False))
        thesis_level, safety_stop, profit_lock, exit_by = compute_orb_exits(
            symbol=sym,
            side=side,
            or_high=setup.or_high,
            or_low=setup.or_low,
            atr14=setup.atr14,
            is_fno=is_fno,
        )

        # 3. Why notification text
        cat_str = " · filing yesterday" if setup.has_catalyst else ""
        gap_str = f"gap {setup.gap_pct:+.1f}%" if abs(setup.gap_pct) >= 0.1 else "flat open"
        why = f"Stock in play: volume {setup.rvol:.1f}× normal in first 5 min · {gap_str}{cat_str}"

        # 4. Mark symbol triggered and update daily cap
        self.triggered_symbols.add(sym)
        self.daily_entries += 1

        return Signal(
            strategy="S2",
            symbol=sym,
            side=side,
            product="MIS",
            ref_price=trigger,
            entry_price=entry_price,
            valid_till=f"{self.cfg.entry_valid_min} min",
            thesis_tf="5m",
            thesis_dir="below" if side == "LONG" else "above",
            thesis_level=thesis_level,
            safety_stop=safety_stop,
            target=None,
            exit_by=exit_by,
            raw_score=float(setup.strength),
            provisional_strength=setup.strength,
            why=why,
            source_url=None,
            profit_lock_rule=None,
            meta={"rvol": setup.rvol, "rank": setup.rvol_rank, "or_high": setup.or_high, "or_low": setup.or_low},
        )

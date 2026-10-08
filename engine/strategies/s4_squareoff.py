"""
Strategy S4: Square-off crush reversal (spec 02 §S4).
Phase A: Event extraction & research measurement into data/research/s4_events.parquet.
Phase B: Live rule (kept behind config flag s4.alerts_enabled: false until promotion).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from engine.config import get_settings
from engine.core.clock import IST
from engine.core.costs import calculate_intraday_costs
from engine.core.models import Candle, Signal
from engine.core.risk import round_tick
from engine.strategies.base import Strategy

logger = logging.getLogger("engine.strategies.s4_squareoff")
RESEARCH_DIR = Path("data/research")


@dataclass
class S4Event:
    date: str
    symbol: str
    is_fno: bool
    adv_cr: float
    prev_close: float
    day_move: float                     # close at 14:55 / 15:05 vs prev_close - 1
    day_move_bucket: str                # "<=-3%", "-3..-1%", "-1..+1%", "+1..+3%", ">=+3%"
    deliv_pct_20d: float
    low_delivery: bool                  # bottom tercile of universe
    minute: str                         # "15:00", "15:05", etc.
    r_m: float                          # close(m) / close(m-1) - 1
    vol_ratio_m: float                  # vol(m) / median minute vol (14:30-14:55)
    bounce_3: float                     # close(m+3) / close(m) - 1
    bounce_5: float                     # close(m+5) / close(m) - 1
    bounce_8: float                     # close(m+8) / close(m) - 1
    had_filing_today: bool


def bucket_day_move(move: float) -> str:
    """Bucket day move per spec 02 §S4.2."""
    if move <= -0.03:
        return "<=-3%"
    elif move <= -0.01:
        return "-3..-1%"
    elif move <= 0.01:
        return "-1..+1%"
    elif move <= 0.03:
        return "+1..+3%"
    else:
        return ">=+3%"


def extract_s4_events_for_day(
    target_date: date,
    candles_df: pd.DataFrame,
    universe_df: pd.DataFrame,
    filings_symbols: Set[str],
) -> List[S4Event]:
    """
    Extract S4 square-off dip and bounce events for a given day (spec 02 §S4.2).
    """
    settings = get_settings()
    cfg = settings.strategies.s4_squareoff
    min_adv = cfg.min_adv_cr

    if candles_df.empty or universe_df.empty:
        return []

    # 1. Filter universe to ADV >= min_adv (5 cr)
    u_adv = universe_df[universe_df["adv_cr"] >= min_adv].copy()
    if u_adv.empty:
        return []

    # 2. Determine low delivery threshold (bottom tercile)
    deliv_threshold = float(u_adv["deliv_pct_20d"].quantile(0.333))

    # Pre-parse timestamps
    candles_df = candles_df.copy()
    candles_df["ts_dt"] = pd.to_datetime(candles_df["ts"])
    if candles_df["ts_dt"].dt.tz is None:
        candles_df["ts_dt"] = candles_df["ts_dt"].dt.tz_localize(IST)
    else:
        candles_df["ts_dt"] = candles_df["ts_dt"].dt.tz_convert(IST)

    candles_df["time_str"] = candles_df["ts_dt"].dt.strftime("%H:%M")
    by_sym = {s: grp.set_index("time_str") for s, grp in candles_df.groupby("symbol")}

    events: List[S4Event] = []

    for _, u_row in u_adv.iterrows():
        sym = str(u_row["symbol"])
        is_fno = bool(u_row.get("fno", False))
        prev_close = float(u_row.get("prev_close", 0.0) or 0.0)
        deliv_pct = float(u_row.get("deliv_pct_20d", 0.0) or 0.0)
        adv = float(u_row.get("adv_cr", 0.0) or 0.0)

        sym_bars = by_sym.get(sym)
        if sym_bars is None or sym_bars.empty or prev_close <= 0:
            continue

        # Day move reference time: 14:55 for F&O, 15:05 for others
        ref_time = "14:55" if is_fno else "15:05"
        if ref_time not in sym_bars.index:
            continue

        ref_close = float(sym_bars.loc[ref_time]["close"])
        day_move = (ref_close / prev_close) - 1.0
        day_bucket = bucket_day_move(day_move)
        low_delivery = deliv_pct <= deliv_threshold

        # Baseline volume 14:30 to 14:55
        vol_baseline_bars = sym_bars.loc[(sym_bars.index >= "14:30") & (sym_bars.index < "14:55")]
        med_vol = float(vol_baseline_bars["volume"].median()) if not vol_baseline_bars.empty else 1000.0
        if med_vol <= 0:
            med_vol = 1000.0

        # Target square-off minutes
        sq_minutes = cfg.minutes_fno if is_fno else cfg.minutes_other
        max_time = "15:14" if is_fno else "15:29"

        for m_str in sq_minutes:
            if m_str not in sym_bars.index:
                continue

            bar_m = sym_bars.loc[m_str]
            c_m = float(bar_m["close"])
            vol_m = int(bar_m["volume"])

            # Prior minute m-1
            m_dt = datetime.strptime(m_str, "%H:%M")
            prev_m_str = (m_dt - timedelta(minutes=1)).strftime("%H:%M")
            if prev_m_str not in sym_bars.index:
                continue

            c_prev = float(sym_bars.loc[prev_m_str]["close"])
            r_m = (c_m / c_prev) - 1.0 if c_prev > 0 else 0.0
            vol_ratio_m = vol_m / med_vol

            # Bounces at m+3, m+5, m+8 (capped at max_time)
            bounces: Dict[int, float] = {}
            for k in [3, 5, 8]:
                target_k_str = (m_dt + timedelta(minutes=k)).strftime("%H:%M")
                if target_k_str > max_time:
                    target_k_str = max_time
                if target_k_str in sym_bars.index:
                    c_k = float(sym_bars.loc[target_k_str]["close"])
                    bounces[k] = (c_k / c_m) - 1.0 if c_m > 0 else 0.0
                else:
                    bounces[k] = 0.0

            had_filing = sym in filings_symbols

            evt = S4Event(
                date=target_date.isoformat(),
                symbol=sym,
                is_fno=is_fno,
                adv_cr=adv,
                prev_close=prev_close,
                day_move=round(day_move, 4),
                day_move_bucket=day_bucket,
                deliv_pct_20d=round(deliv_pct, 2),
                low_delivery=low_delivery,
                minute=m_str,
                r_m=round(r_m, 4),
                vol_ratio_m=round(vol_ratio_m, 2),
                bounce_3=round(bounces.get(3, 0.0), 4),
                bounce_5=round(bounces.get(5, 0.0), 4),
                bounce_8=round(bounces.get(8, 0.0), 4),
                had_filing_today=had_filing,
            )
            events.append(evt)

    return events


def append_s4_events(events: List[S4Event], output_dir: Path | str = RESEARCH_DIR) -> Path:
    """Append newly extracted events to data/research/s4_events.parquet."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "s4_events.parquet"

    new_df = pd.DataFrame([asdict(e) for e in events])
    if parquet_path.exists():
        existing_df = pd.read_parquet(parquet_path)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        # Dedupe by date, symbol, minute
        combined_df.drop_duplicates(subset=["date", "symbol", "minute"], keep="last", inplace=True)
    else:
        combined_df = new_df

    combined_df.to_parquet(parquet_path, index=False)
    logger.info(f"Saved {len(combined_df)} S4 events to {parquet_path}")
    return parquet_path


def build_s4_research_report(parquet_path: Path | str = RESEARCH_DIR / "s4_events.parquet") -> Dict[str, Any]:
    """
    Generate grouped research summary table from stored S4 events per spec 02 §S4.2.
    Groups by: is_fno x day_move_bucket x low_delivery x minute.
    """
    p_path = Path(parquet_path)
    if not p_path.exists():
        return {"total_events": 0, "sessions": 0, "groups": [], "simulated_trades": []}

    df = pd.read_parquet(p_path)
    if df.empty:
        return {"total_events": 0, "sessions": 0, "groups": [], "simulated_trades": []}

    sessions = df["date"].nunique()
    total_events = len(df)

    groups = []
    # Group by {is_fno} x {day_move_bucket} x {low_delivery}
    for (fno, d_bucket, low_del), grp in df.groupby(["is_fno", "day_move_bucket", "low_delivery"]):
        n = len(grp)
        mean_r = float(grp["r_m"].mean() * 100.0)
        mean_b5 = float(grp["bounce_5"].mean() * 100.0)
        std_b5 = float(grp["bounce_5"].std() * 100.0) if n > 1 else 0.0
        t_stat = (mean_b5 / (std_b5 / math.sqrt(n))) if std_b5 > 0 and n > 1 else 0.0
        hit_rate = float((grp["bounce_5"] > 0).mean() * 100.0)

        groups.append({
            "is_fno": bool(fno),
            "day_move_bucket": str(d_bucket),
            "low_delivery": bool(low_del),
            "n": n,
            "mean_r_m_pct": round(mean_r, 2),
            "mean_bounce_5_pct": round(mean_b5, 2),
            "t_stat": round(t_stat, 2),
            "hit_rate_pct": round(hit_rate, 1),
        })

    # Simulated trades per spec 02 §S4.2:
    # Buy at close of m when r_m <= -0.5% and day_move <= -3% and low_delivery and no filing
    cand = df[
        (df["r_m"] <= -0.005) &
        (df["day_move"] <= -0.03) &
        (df["low_delivery"] == True) &
        (df["had_filing_today"] == False)
    ].copy()

    simulated_trades = []
    for _, row in cand.iterrows():
        gross = float(row["bounce_5"] * 100.0)
        # Cost estimate (Zerodha CNC buy and sell same day intraday) ~0.15%
        net = round(gross - 0.15, 2)
        simulated_trades.append({
            "date": row["date"],
            "symbol": row["symbol"],
            "minute": row["minute"],
            "dip_pct": round(float(row["r_m"] * 100.0), 2),
            "bounce_5_pct": round(gross, 2),
            "net_pnl_pct": net,
        })

    return {
        "total_events": total_events,
        "sessions": sessions,
        "groups": groups,
        "simulated_trades": simulated_trades,
    }


class S4SquareoffStrategy(Strategy):
    """
    S4 Live Strategy (spec 02 §S4.4).
    Alerts remain disabled until s4.alerts_enabled: true in config.yaml.
    """

    def __init__(self):
        super().__init__("S4")
        self.settings = get_settings()
        self.cfg = self.settings.strategies.s4_squareoff
        self.universe_map: Dict[str, dict] = {}
        self.filings_today: Set[str] = set()

    def on_start(self, universe_df: pd.DataFrame) -> None:
        self.universe_map = {row["symbol"]: row.to_dict() for _, row in universe_df.iterrows()}
        self.filings_today.clear()

    async def on_filing(self, filing: Dict[str, Any], current_price: Optional[float] = None, **kwargs) -> Optional[Signal]:
        sym = filing.get("symbol")
        if sym:
            self.filings_today.add(sym)
        return None

    def on_candle_1m(self, candle: Candle) -> Optional[Signal]:
        """
        Evaluate square-off crush reversal trigger at minute m close.
        Only generates signal if alerts_enabled is True.
        """
        if not self.cfg.alerts_enabled:
            return None

        sym = candle.symbol
        if sym in self.filings_today:
            return None

        u = self.universe_map.get(sym, {})
        is_fno = bool(u.get("fno", False))
        sq_minutes = self.cfg.minutes_fno if is_fno else self.cfg.minutes_other

        c_ts = getattr(candle, "timestamp", getattr(candle, "ts", None))
        if not c_ts:
            return None

        m_str = c_ts.strftime("%H:%M")
        if m_str not in sq_minutes:
            return None

        # Check minute dip: r_m <= -0.5%
        # Candle open to close dip
        dip_pct = ((candle.close / candle.open) - 1.0) * 100.0
        if dip_pct > -self.cfg.min_minute_drop_pct:
            return None

        # S4 trade is CNC, full cash, Long only
        entry_price = round_tick(candle.close * (1.0 + self.cfg.entry_slip_pct / 100.0))
        safety_stop = round_tick(candle.close * (1.0 - self.cfg.safety_stop_pct / 100.0))

        # Time exit: m + hold_min (capped at 15:14 / 15:29)
        exit_dt = c_ts + timedelta(minutes=self.cfg.hold_min)
        max_t = time(15, 14) if is_fno else time(15, 29)
        if exit_dt.time() > max_t:
            exit_dt = exit_dt.replace(hour=max_t.hour, minute=max_t.minute)

        exit_by = exit_dt.strftime("%H:%M")
        why = f"Square-off crush: {dip_pct:.1f}% dip in {m_str} broker wave · low delivery · CNC"

        return Signal(
            strategy="S4",
            symbol=sym,
            side="LONG",
            product="CNC",
            ref_price=candle.close,
            entry_price=entry_price,
            valid_till="1 min",
            thesis_tf="1m",
            thesis_dir="below",
            thesis_level=None,
            safety_stop=safety_stop,
            target=None,
            exit_by=exit_by,
            raw_score=6.0,
            provisional_strength=6,
            why=why,
        )

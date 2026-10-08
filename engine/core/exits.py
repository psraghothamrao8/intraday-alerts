"""
Exit engine (spec 03 §2, §4, §7).
Evaluates three exit layers:
  1. Time exit (main horizon exit or last_exit_time)
  2. Thesis stop (evaluated strictly on completed 5-minute candle closes)
  3. Safety stop (evaluated on ticks / price prints)
  + Profit lock (optional anchored VWAP trail after +2% gain)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple

from engine.config import get_settings
from engine.core.calendar import last_exit_time
from engine.core.costs import calculate_intraday_costs
from engine.core.models import Candle, Tick, Trade
from engine.core.risk import round_tick, avoid_round_numbers


def compute_news_exits(
    symbol: str,
    side: str,
    entry_price: float,
    ref_price: float,
    atr14: float,
    is_fno: bool = False,
    k_safe: float = 1.0,
    profit_lock: str = "avwap_after_2pct"
) -> Tuple[float, float, str, str]:
    """
    Computes News Exit Template (S1/S3) per spec 03 §4.1:
      Returns (thesis_level, safety_stop, profit_lock_rule, exit_by_hhmm)
    """
    is_long = side.upper() == "LONG"
    atr = max(0.5, atr14)

    if is_long:
        thesis_level = round_tick(ref_price - 0.1 * atr)
        safety_raw = min(entry_price - k_safe * atr, thesis_level - 0.25 * atr)
        safety_stop = avoid_round_numbers(safety_raw, side="LONG")
    else:
        thesis_level = round_tick(ref_price + 0.1 * atr)
        safety_raw = max(entry_price + k_safe * atr, thesis_level + 0.25 * atr)
        safety_stop = avoid_round_numbers(safety_raw, side="SHORT")

    exit_dt = last_exit_time(symbol, is_fno=is_fno)
    exit_by = exit_dt.strftime("%H:%M")

    return thesis_level, safety_stop, profit_lock, exit_by


def compute_orb_exits(
    symbol: str,
    side: str,
    or_high: float,
    or_low: float,
    atr14: float,
    is_fno: bool = False,
) -> Tuple[float, float, Optional[str], str]:
    """
    Computes ORB Exit Template (S2) per spec 03 §4.2:
      Returns (thesis_level, safety_stop, profit_lock_rule, exit_by_hhmm)
    """
    is_long = side.upper() == "LONG"
    atr = max(0.5, atr14)

    if is_long:
        thesis_level = round_tick(or_low)
        safety_raw = or_low - 0.25 * atr
        safety_stop = avoid_round_numbers(safety_raw, side="LONG")
    else:
        thesis_level = round_tick(or_high)
        safety_raw = or_high + 0.25 * atr
        safety_stop = avoid_round_numbers(safety_raw, side="SHORT")

    exit_dt = last_exit_time(symbol, is_fno=is_fno)
    exit_by = exit_dt.strftime("%H:%M")

    return thesis_level, safety_stop, None, exit_by


@dataclass
class ExitEvent:
    trade_id: str
    symbol: str
    exit_time: str
    exit_price: float
    exit_reason: str
    net_pnl_pct: float
    net_pnl_inr: float


class ExitEngine:
    """Evaluates exit conditions for open trades across ticks, 5m candles, and clock."""

    def __init__(self):
        self.settings = get_settings()

    def evaluate_tick(self, trade: Trade, tick: Tick) -> Optional[ExitEvent]:
        """
        Layer 3: Safety stop.
        Triggers if price touches safety_stop.
        """
        if trade.status != "OPEN":
            return None

        is_long = trade.side.upper() == "LONG"
        hit = False

        if is_long and tick.ltp <= trade.safety_stop:
            hit = True
        elif not is_long and tick.ltp >= trade.safety_stop:
            hit = True

        if hit:
            # Paper execution price: safety stop or tick LTP if gapped through
            exit_price = tick.ltp
            reason = "safety stop hit: your SL order should have filled"
            return self._create_exit_event(trade, exit_price, reason, tick.timestamp.isoformat())

        return None

    def evaluate_candle_5m(
        self,
        trade: Trade,
        candle: Candle,
        anchored_vwap: Optional[float] = None,
    ) -> Optional[ExitEvent]:
        """
        Layer 2: Thesis stop and profit lock.
        Evaluated ONLY on completed 5-minute candle closes (+2 s).
        Wicks (high/low) DO NOT count for thesis stops.
        """
        if trade.status != "OPEN":
            return None

        is_long = trade.side.upper() == "LONG"
        entry_price = trade.paper_entry or trade.ref_price

        # 1. Thesis stop evaluation (5m close beyond level)
        if trade.thesis_level is not None:
            if is_long and candle.close <= trade.thesis_level:
                reason = f"thesis broken: 5m closed below ₹{trade.thesis_level:.2f}"
                return self._create_exit_event(trade, candle.close, reason, candle.timestamp.isoformat())
            elif not is_long and candle.close >= trade.thesis_level:
                reason = f"thesis broken: 5m closed above ₹{trade.thesis_level:.2f}"
                return self._create_exit_event(trade, candle.close, reason, candle.timestamp.isoformat())

        # 2. Profit lock evaluation
        if trade.profit_lock_rule:
            # Activation check: +2% gain on 5m close
            if not trade.profit_lock_active:
                if is_long and candle.close >= entry_price * 1.02:
                    trade.profit_lock_active = True
                elif not is_long and candle.close <= entry_price * 0.98:
                    trade.profit_lock_active = True

            # Trigger check if activated
            if trade.profit_lock_active and anchored_vwap is not None:
                if is_long and candle.close < anchored_vwap:
                    reason = f"profit lock: 5m closed below anchored VWAP ₹{anchored_vwap:.2f}"
                    return self._create_exit_event(trade, candle.close, reason, candle.timestamp.isoformat())
                elif not is_long and candle.close > anchored_vwap:
                    reason = f"profit lock: 5m closed above anchored VWAP ₹{anchored_vwap:.2f}"
                    return self._create_exit_event(trade, candle.close, reason, candle.timestamp.isoformat())

        return None

    def evaluate_clock(
        self,
        trade: Trade,
        now: datetime,
        current_price: Optional[float] = None,
        is_fno: bool = False
    ) -> Optional[ExitEvent]:
        """
        Layer 1: Time exit.
        Triggers when current time reaches trade.exit_by or last_exit_time(symbol).
        """
        if trade.status != "OPEN":
            return None

        # Check explicit trade.exit_by
        exit_time_str = trade.exit_by.strip()
        time_hit = False
        reason = ""

        # Check format HH:MM
        if len(exit_time_str) >= 5 and ":" in exit_time_str:
            cur_hhmm = now.strftime("%H:%M")
            if cur_hhmm >= exit_time_str:
                time_hit = True
                reason = f"time exit: reached {exit_time_str}"

        # Also check calendar last_exit_time
        calc_last_exit = last_exit_time(trade.symbol, is_fno=is_fno, on_date=now.date())
        if now >= calc_last_exit:
            time_hit = True
            reason = f"time exit: reached last exit cutoff {calc_last_exit.strftime('%H:%M')}"

        if time_hit:
            exit_price = current_price if current_price is not None else (trade.paper_entry or trade.ref_price)
            return self._create_exit_event(trade, exit_price, reason, now.isoformat())

        return None

    def _create_exit_event(
        self,
        trade: Trade,
        exit_price: float,
        reason: str,
        timestamp_str: str,
    ) -> ExitEvent:
        """Construct ExitEvent and calculate net P&L after costs."""
        entry_price = trade.paper_entry or trade.ref_price
        is_long = trade.side.upper() == "LONG"

        if is_long:
            gross_pnl_inr = trade.qty * (exit_price - entry_price)
            buy_val = trade.qty * entry_price
            sell_val = trade.qty * exit_price
        else:
            gross_pnl_inr = trade.qty * (entry_price - exit_price)
            buy_val = trade.qty * exit_price
            sell_val = trade.qty * entry_price

        costs_inr = calculate_intraday_costs(buy_val, sell_val)
        net_pnl_inr = gross_pnl_inr - costs_inr
        net_pnl_pct = (net_pnl_inr / buy_val * 100.0) if buy_val > 0 else 0.0

        # Mark trade as EXITED
        trade.status = "EXITED"
        trade.exit_time = timestamp_str
        trade.exit_price = exit_price
        trade.exit_reason = reason
        trade.paper_net_pct = round(net_pnl_pct, 2)

        return ExitEvent(
            trade_id=trade.id,
            symbol=trade.symbol,
            exit_time=timestamp_str,
            exit_price=exit_price,
            exit_reason=reason,
            net_pnl_pct=net_pnl_pct,
            net_pnl_inr=net_pnl_inr,
        )

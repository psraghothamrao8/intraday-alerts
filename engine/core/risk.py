"""
Risk management and position sizing engine (spec 03 §2, §3, §6).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from engine.config import get_settings
from engine.core.models import Signal, Trade


def round_tick(price: float, tick: float = 0.05) -> float:
    """Round price to nearest instrument tick size."""
    if tick <= 0:
        return round(price, 2)
    return round(round(price / tick) * tick, 2)


def calculate_position_size(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    adv_cr: float = 10.0,
    product: str = "MIS",
) -> Tuple[int, float]:
    """Helper for sizing calculation."""
    rm = RiskManager()
    qty, risk_inr, skip = rm.calculate_quantity(entry_price, stop_loss, product=product, adv_cr=adv_cr)
    if skip:
        return 0, 0.0
    return qty, risk_inr


def avoid_round_numbers(stop_price: float, side: str = "LONG") -> float:
    """
    Spec 03 §3 rule 3:
    Avoid round numbers: if a stop lies within 0.15% of a multiple of ₹10 (price < ₹1,000),
    ₹50 (₹1,000–5,000) or ₹100 (above), move it 0.15% beyond that multiple (further from entry).
    """
    p = float(stop_price)
    if p <= 0:
        return p

    if p < 1000.0:
        step = 10.0
    elif p <= 5000.0:
        step = 50.0
    else:
        step = 100.0

    nearest_multiple = round(p / step) * step
    dist_pct = abs(p - nearest_multiple) / p

    if dist_pct < 0.0015:
        # Move 0.15% beyond that multiple (further from entry)
        if side.upper() == "LONG":
            # For LONG, stop is below entry -> move lower
            adjusted = nearest_multiple - (0.0015 * nearest_multiple)
        else:
            # For SHORT, stop is above entry -> move higher
            adjusted = nearest_multiple + (0.0015 * nearest_multiple)
        return round_tick(adjusted)
    return round_tick(p)


class RiskManager:
    """
    Enforces sizing rules and day-level risk limits.
    Runs on paper P&L.
    """

    def __init__(self):
        self.settings = get_settings()
        self.capital = float(self.settings.capital_inr)
        self.risk_cfg = self.settings.risk

        self.consecutive_losses: int = 0
        self.daily_loss_tripped: bool = False
        self.alert_sent: bool = False
        self.trades_today: List[Trade] = []

    def reset_day(self) -> None:
        """Reset day-level state at market start."""
        self.consecutive_losses = 0
        self.daily_loss_tripped = False
        self.alert_sent = False
        self.trades_today = []

    def calculate_quantity(
        self,
        entry: float,
        safety_stop: float,
        product: str = "MIS",
        adv_cr: float = 10.0,
    ) -> Tuple[int, float, Optional[str]]:
        """
        Position sizing rule per spec 03 §2:
          risk_inr = capital * risk_per_trade_pct (0.5%)
          qty = floor( min( risk_inr / |entry - safety_stop|,
                            max_notional / entry,
                            liquidity_cap_inr / entry ) )
          skip trade if qty * entry < min_notional_inr (₹5,000)

        Returns (qty, risk_inr, skip_reason)
        """
        if entry <= 0:
            return 0, 0.0, "invalid_entry_price"

        stop_dist = abs(entry - safety_stop)
        if stop_dist <= 0:
            return 0, 0.0, "zero_stop_distance"

        risk_pct = self.risk_cfg.risk_per_trade_pct / 100.0
        risk_inr = self.capital * risk_pct

        if product.upper() == "CNC":
            max_notional_pct = self.risk_cfg.max_notional_pct_cnc / 100.0
        else:
            max_notional_pct = self.risk_cfg.max_notional_pct_mis / 100.0
        max_notional = self.capital * max_notional_pct

        liq_pct = self.risk_cfg.liquidity_cap_pct_adv / 100.0
        liq_cap_inr = (adv_cr * 1e7) * liq_pct

        cap_from_risk = risk_inr / stop_dist
        cap_from_notional = max_notional / entry
        cap_from_liq = liq_cap_inr / entry

        qty = math.floor(min(cap_from_risk, cap_from_notional, cap_from_liq))

        if qty <= 0:
            return 0, 0.0, "skipped:zero_qty"

        notional = qty * entry
        if notional < self.risk_cfg.min_notional_inr:
            return 0, 0.0, f"skipped:below_min_notional:{notional:.0f}<{self.risk_cfg.min_notional_inr}"

        # Actual risk incurred with floor(qty)
        actual_risk_inr = qty * stop_dist
        return qty, actual_risk_inr, None

    def can_enter_trade(
        self,
        signal: Signal,
        open_trades: List[Trade],
        universe_row: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check whether a candidate signal can enter a new trade based on day-level limits.
        Spec 03 §6 and Spec 02 §1.
        """
        if self.daily_loss_tripped:
            return False, "skipped:daily_loss_stop_active"

        if self.consecutive_losses >= self.risk_cfg.max_consecutive_losses:
            return False, f"skipped:max_consecutive_losses:{self.consecutive_losses}"

        if len(open_trades) >= self.risk_cfg.max_open_trades:
            return False, f"skipped:max_open_trades_reached:{len(open_trades)}"

        if len(self.trades_today) >= self.risk_cfg.max_entries_per_day:
            return False, f"skipped:max_entries_per_day_reached:{len(self.trades_today)}"

        # S2 max 3 trades per day
        if signal.strategy.upper() == "S2":
            s2_today = sum(1 for t in self.trades_today if t.strategy.upper() == "S2")
            if s2_today >= 3:
                return False, f"skipped:max_s2_entries_reached:{s2_today}"

        # Never two open trades in the same symbol
        if any(t.symbol == signal.symbol for t in open_trades):
            return False, f"skipped:already_open_in_symbol:{signal.symbol}"

        # One entry per symbol per strategy per day
        if any(t.symbol == signal.symbol and t.strategy == signal.strategy for t in self.trades_today):
            return False, f"skipped:already_entered_symbol_strategy_today:{signal.symbol}"

        # Short selling checks
        if signal.side.upper() == "SHORT":
            if universe_row:
                if not universe_row.get("mis_allowed", True):
                    return False, "skipped:short_mis_not_allowed"
                is_fno = bool(universe_row.get("fno", False))
                # F&O stocks or band room >= 10%
                # In universe, band_room can be estimated or passed in meta
                band_room = signal.meta.get("band_room", 1.0 if is_fno else 0.10)
                if not is_fno and band_room < 0.10:
                    return False, "skipped:short_band_room_under_10pct"

        return True, None

    def record_entry(self, trade: Trade) -> None:
        """Record trade entry for daily count tracking."""
        self.trades_today.append(trade)

    def on_trade_closed(self, trade: Trade, net_pnl_inr: float) -> Optional[str]:
        """
        Record closed trade result and update consecutive losses / daily loss limits.
        Returns alert message if loss stop is tripped.
        """
        if net_pnl_inr < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Check consecutive losses limit
        if self.consecutive_losses >= self.risk_cfg.max_consecutive_losses and not self.alert_sent:
            self.daily_loss_tripped = True
            self.alert_sent = True
            return f"Max consecutive losses ({self.consecutive_losses}) hit. Trading paused for the day."

        # Check daily loss limit
        realized_loss = sum(
            (t.qty * ((t.exit_price or 0.0) - (t.paper_entry or 0.0)) * (1 if t.side == "LONG" else -1))
            for t in self.trades_today
            if t.status == "EXITED" and t.exit_price is not None and t.paper_entry is not None
        )
        max_daily_loss = self.capital * (self.risk_cfg.daily_loss_stop_pct / 100.0)
        if realized_loss <= -max_daily_loss and not self.alert_sent:
            self.daily_loss_tripped = True
            self.alert_sent = True
            return f"Daily loss limit (₹{abs(realized_loss):.0f} >= ₹{max_daily_loss:.0f}) hit. Trading paused for the day."

        return None

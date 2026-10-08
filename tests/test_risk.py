"""
Acceptance tests for RiskManager (spec 07 Task 4).
Tests:
  - Quantity sizing formula and caps
  - Daily loss stop blocks new entries
  - Max open trades limit
  - Avoid round numbers adjustment
"""
import pytest
from engine.core.models import Signal, Trade
from engine.core.risk import RiskManager, avoid_round_numbers


def test_avoid_round_numbers():
    """Verify round number avoidance per spec 03 §3."""
    # Price < 1000: step = 10. Round multiple = 500.
    # 500 * 0.0015 = 0.75. Range [499.25, 500.75]
    # For LONG stop at 500.0, moves down to 500 - 0.75 = 499.25
    adj_long = avoid_round_numbers(500.0, side="LONG")
    assert adj_long == 499.25

    # For SHORT stop at 500.0, moves up to 500 + 0.75 = 500.75
    adj_short = avoid_round_numbers(500.0, side="SHORT")
    assert adj_short == 500.75

    # A stop well away from round numbers (e.g. 505.0) remains untouched
    assert avoid_round_numbers(505.0, side="LONG") == 505.0


def test_quantity_formula_sizing_and_caps():
    """
    Verify qty formula per spec 03 §2:
      risk_inr = capital * 0.5% (2500 on 500k)
      qty = floor( min( risk / stop_dist, max_notional / entry, liq_cap / entry ) )
    """
    rm = RiskManager()
    rm.capital = 500000.0  # 5 Lakhs -> 0.5% risk = ₹2500

    # Case 1: Standard risk-limited trade
    # Entry 1000, safety stop 950 (stop distance 50).
    # Risk-based qty = 2500 / 50 = 50 shares.
    # Notional = 50 * 1000 = 50,000 (well within 200% MIS cap = 1,000,000).
    # Liquidity cap for ADV 20 cr: 20 cr * 0.5% = 10 Lakhs.
    qty, risk, skip = rm.calculate_quantity(entry=1000.0, safety_stop=950.0, adv_cr=20.0)
    assert skip is None
    assert qty == 50
    assert risk == 2500.0

    # Case 2: Below min notional (₹5000)
    # Entry 100, stop 50 (dist 50). Very low capital or tight cap
    # If qty * entry < 5000 -> skips
    qty_low, _, skip_low = rm.calculate_quantity(entry=100.0, safety_stop=10.0, adv_cr=0.001)
    # adv 0.001 cr = 10,000 INR -> 0.5% liq cap = 50 INR -> qty = 0
    assert qty_low == 0
    assert "skipped" in skip_low


def test_max_open_trades_blocks_new_entries():
    """Verify that reaching max_open_trades blocks new entries."""
    rm = RiskManager()
    rm.reset_day()

    open_trades = [
        Trade(
            id=f"T{i}", strategy="S1", symbol=f"SYM{i}", side="LONG", product="MIS",
            signal_time="10:00", ref_price=100.0, max_entry=101.0, valid_till="10:05",
            qty=10, risk_inr=500.0, safety_stop=95.0, exit_by="15:00", status="OPEN"
        )
        for i in range(4)  # 4 open trades (max is 4)
    ]

    sig = Signal(
        strategy="S1", symbol="NEWSTOCK", side="LONG", product="MIS",
        ref_price=200.0, entry_price=201.0, valid_till="10:10", safety_stop=190.0,
        exit_by="15:00"
    )

    allowed, reason = rm.can_enter_trade(sig, open_trades)
    assert allowed is False
    assert "max_open_trades_reached" in reason


def test_daily_loss_stop_blocks_new_entries():
    """Verify daily loss stop (2% of capital) trips and blocks new entries."""
    rm = RiskManager()
    rm.reset_day()
    rm.capital = 500000.0  # 2% is ₹10,000

    # Create a losing trade with ₹12,000 loss
    losing_trade = Trade(
        id="T_LOSS", strategy="S1", symbol="LOSER", side="LONG", product="MIS",
        signal_time="10:00", ref_price=1000.0, max_entry=1000.0, paper_entry=1000.0,
        valid_till="10:05", qty=100, risk_inr=5000.0, safety_stop=950.0, exit_by="15:00",
        status="EXITED", exit_price=880.0, exit_time="10:30"
    )
    rm.record_entry(losing_trade)
    alert = rm.on_trade_closed(losing_trade, net_pnl_inr=-12000.0)

    assert alert is not None
    assert "Daily loss limit" in alert
    assert rm.daily_loss_tripped is True

    # Next candidate trade should be blocked
    sig = Signal(
        strategy="S1", symbol="ANOTHER", side="LONG", product="MIS",
        ref_price=500.0, entry_price=502.0, valid_till="11:00", safety_stop=480.0, exit_by="15:00"
    )
    allowed, reason = rm.can_enter_trade(sig, open_trades=[])
    assert allowed is False
    assert "daily_loss_stop_active" in reason

"""
Tests for Strategy S4: Square-off crush reversal (spec 02 §S4).
Validates:
1. Event extraction math (day_move, low_delivery bottom tercile, r_m, vol_ratio_m, bounce_k).
2. Research summary aggregation table and simulated trade calculations.
3. Live rule gating (alerts_enabled: false vs true, CNC product, safety stop).
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import pytest
import pandas as pd

from engine.core.clock import IST
from engine.core.models import Candle
from engine.strategies.s4_squareoff import (
    S4Event,
    S4SquareoffStrategy,
    append_s4_events,
    bucket_day_move,
    build_s4_research_report,
    extract_s4_events_for_day,
)


def create_synthetic_session() -> tuple[pd.DataFrame, pd.DataFrame]:
    # 3 stocks: FNO_DOWN (down > 3%), FNO_UP (up 2%), CASH_DOWN (non-fno down 4%)
    universe_df = pd.DataFrame([
        {
            "symbol": "FNO_DOWN", "fno": True, "prev_close": 1000.0,
            "adv_cr": 20.0, "deliv_pct_20d": 20.0  # lowest delivery
        },
        {
            "symbol": "FNO_UP", "fno": True, "prev_close": 500.0,
            "adv_cr": 15.0, "deliv_pct_20d": 45.0  # middle delivery
        },
        {
            "symbol": "CASH_DOWN", "fno": False, "prev_close": 200.0,
            "adv_cr": 8.0, "deliv_pct_20d": 60.0  # high delivery
        },
    ])

    candle_rows = []
    # Generate 1m bars from 14:25 to 15:30
    cur_t = datetime(2026, 10, 8, 14, 25, 0, tzinfo=IST)
    end_t = datetime(2026, 10, 8, 15, 30, 0, tzinfo=IST)

    while cur_t <= end_t:
        t_str = cur_t.strftime("%H:%M")

        # FNO_DOWN: down 4% by 14:55 (960.0), dips sharply at 15:00 to 950.0 (-1.04%), bounces to 965.0 by 15:05 (+1.58%)
        if t_str < "14:55":
            p1 = 965.0
            v1 = 1000
        elif t_str == "14:55":
            p1 = 960.0
            v1 = 1200
        elif t_str == "14:59":
            p1 = 960.0
            v1 = 1000
        elif t_str == "15:00":
            p1 = 950.0  # r_m = 950/960 - 1 = -1.04%
            v1 = 3000  # volume spike
        elif t_str == "15:05":
            p1 = 965.0  # bounce_5 = 965/950 - 1 = +1.58%
            v1 = 1500
        else:
            p1 = 962.0
            v1 = 1000

        candle_rows.append({"symbol": "FNO_DOWN", "ts": cur_t.isoformat(), "open": p1, "high": p1 + 1, "low": p1 - 1, "close": p1, "volume": v1})

        # FNO_UP: flat / up
        p2 = 510.0
        candle_rows.append({"symbol": "FNO_UP", "ts": cur_t.isoformat(), "open": p2, "high": p2 + 1, "low": p2 - 1, "close": p2, "volume": 1000})

        # CASH_DOWN: down 3.5% at 15:05 (193.0)
        p3 = 193.0
        candle_rows.append({"symbol": "CASH_DOWN", "ts": cur_t.isoformat(), "open": p3, "high": p3 + 1, "low": p3 - 1, "close": p3, "volume": 1000})

        cur_t += timedelta(minutes=1)

    return pd.DataFrame(candle_rows), universe_df


def test_s4_event_extraction_math():
    candles_df, universe_df = create_synthetic_session()
    events = extract_s4_events_for_day(
        target_date=date(2026, 10, 8),
        candles_df=candles_df,
        universe_df=universe_df,
        filings_symbols=set(),
    )

    assert len(events) > 0
    # Find FNO_DOWN event at 15:00
    e_1500 = next(e for e in events if e.symbol == "FNO_DOWN" and e.minute == "15:00")

    # Day move: (960.0 / 1000.0) - 1 = -4.0%
    assert e_1500.day_move == pytest.approx(-0.04, abs=0.001)
    assert e_1500.day_move_bucket == "<=-3%"
    assert e_1500.low_delivery is True

    # Dip r_m: 950 / 960 - 1 = -0.0104 (-1.04%)
    assert e_1500.r_m == pytest.approx(-0.0104, abs=0.001)
    assert e_1500.vol_ratio_m >= 2.5  # 3000 / 1000 = 3.0

    # Bounce_5: 965 / 950 - 1 = +0.0158 (+1.58%)
    assert e_1500.bounce_5 == pytest.approx(0.0158, abs=0.001)


def test_s4_research_aggregation_and_simulated_trade(tmp_path):
    candles_df, universe_df = create_synthetic_session()
    events = extract_s4_events_for_day(
        target_date=date(2026, 10, 8),
        candles_df=candles_df,
        universe_df=universe_df,
        filings_symbols=set(),
    )

    parquet_file = append_s4_events(events, output_dir=tmp_path)
    assert parquet_file.exists()

    report = build_s4_research_report(parquet_file)
    assert report["total_events"] == len(events)
    assert report["sessions"] == 1
    assert len(report["groups"]) > 0

    # Simulated trade must match FNO_DOWN at 15:00
    sim_trades = report["simulated_trades"]
    assert len(sim_trades) == 1
    assert sim_trades[0]["symbol"] == "FNO_DOWN"
    assert sim_trades[0]["minute"] == "15:00"
    assert sim_trades[0]["dip_pct"] < -0.5
    assert sim_trades[0]["bounce_5_pct"] > 1.0
    assert sim_trades[0]["net_pnl_pct"] > 0.5  # Net of transaction costs


def test_s4_live_strategy_gating():
    strat = S4SquareoffStrategy()
    _, universe_df = create_synthetic_session()
    strat.on_start(universe_df)

    # 1. Gated: alerts_enabled is False by default
    ts = datetime(2026, 10, 8, 15, 0, 0, tzinfo=IST)
    c_dip = Candle(symbol="FNO_DOWN", timestamp=ts, open=960.0, high=960.0, low=948.0, close=950.0, volume=3000)
    sig_gated = strat.on_candle_1m(c_dip)
    assert sig_gated is None, "S4 must not alert when alerts_enabled is False"

    # 2. Enabled: manually enable for testing
    strat.cfg.alerts_enabled = True
    sig_active = strat.on_candle_1m(c_dip)
    assert sig_active is not None
    assert sig_active.strategy == "S4"
    assert sig_active.product == "CNC"
    assert sig_active.side == "LONG"
    assert sig_active.safety_stop < sig_active.entry_price
    assert sig_active.thesis_level is None  # No thesis stop for S4
    assert sig_active.exit_by == "15:05"    # 5 min hold

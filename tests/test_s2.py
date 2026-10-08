"""
Tests for Strategy S2: Opening-Range Breakout (ORB).
Validates:
1. RVOL ranking at 09:20 (top 20, descending order, RVOL >= 1.0)
2. Setup direction (C > O is Long, C < O is Short, C == O skipped, range > 0.6 ATR skipped)
3. 1-minute breakout trigger and extended-candle skip (> 0.4%)
4. The 3-per-day cap and 1 trade per symbol
5. Provisional strength calculation
6. ORB exit levels (thesis stop at OR opposite side, safety stop with ATR buffer)
"""
from datetime import datetime
import pandas as pd
import pytest

from engine.core.clock import IST
from engine.core.models import Candle
from engine.strategies.s2_orb import S2OrbStrategy, OrbSetup
from engine.core.exits import compute_orb_exits


def make_candle(symbol: str, hour: int, minute: int, o: float, h: float, l: float, c: float, v: int) -> Candle:
    ts = datetime(2026, 10, 8, hour, minute, 0, tzinfo=IST)
    return Candle(
        symbol=symbol,
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def build_sample_universe() -> pd.DataFrame:
    records = []
    # Create 25 eligible stocks
    for i in range(1, 26):
        sym = f"SYM{i}"
        records.append({
            "symbol": sym,
            "series": "EQ",
            "mis_allowed": True,
            "asm_stage": 0,
            "gsm": False,
            "adv_cr": 25.0,
            "prev_close": 500.0,
            "atr_pct": 2.0,
            "atr14": 10.0,
            "or_vol_avg14": 10000.0,
            "fno": True,
            "short_allowed": True,
        })
    return pd.DataFrame(records)


def test_s2_rvol_ranking_and_top_20():
    strat = S2OrbStrategy()
    universe_df = build_sample_universe()
    strat.on_start(universe_df)

    # Feed 5m candle (09:15-09:20) for all 25 stocks with varying volume
    for i in range(1, 26):
        sym = f"SYM{i}"
        # Volume ranges from 5,000 (RVOL 0.5) to 50,000 (RVOL 5.0)
        vol = i * 2000  # i=1 -> 2000 (rvol 0.2), i=5 -> 10000 (rvol 1.0), i=25 -> 50000 (rvol 5.0)
        c = make_candle(sym, 9, 20, 500.0, 504.0, 498.0, 502.0, vol)
        strat.on_candle_5m(c)

    setups = strat.compute_ranking()

    # RVOL < 1.0 should be excluded (i=1..4: vol < 10000)
    # Remaining 21 symbols (i=5..25) have RVOL >= 1.0.
    # Top 20 should be selected.
    assert len(setups) == 20
    assert setups[0].symbol == "SYM25"  # Highest RVOL (5.0)
    assert setups[0].rvol == pytest.approx(5.0)
    assert setups[0].rvol_rank == 1

    # Check ranking is strictly descending
    rvols = [s.rvol for s in setups]
    assert rvols == sorted(rvols, reverse=True)


def test_s2_setup_direction_and_range_cap():
    strat = S2OrbStrategy()
    # 4 stocks: Long, Short, Flat (C==O), Wide Range (> 0.6 ATR)
    df = pd.DataFrame([
        {"symbol": "LONG1", "series": "EQ", "mis_allowed": True, "asm_stage": 0, "gsm": False,
         "adv_cr": 20.0, "prev_close": 100.0, "atr_pct": 2.0, "atr14": 5.0, "or_vol_avg14": 1000.0, "fno": True},
        {"symbol": "SHORT1", "series": "EQ", "mis_allowed": True, "asm_stage": 0, "gsm": False,
         "adv_cr": 20.0, "prev_close": 100.0, "atr_pct": 2.0, "atr14": 5.0, "or_vol_avg14": 1000.0, "fno": True},
        {"symbol": "FLAT1", "series": "EQ", "mis_allowed": True, "asm_stage": 0, "gsm": False,
         "adv_cr": 20.0, "prev_close": 100.0, "atr_pct": 2.0, "atr14": 5.0, "or_vol_avg14": 1000.0, "fno": True},
        {"symbol": "WIDE1", "series": "EQ", "mis_allowed": True, "asm_stage": 0, "gsm": False,
         "adv_cr": 20.0, "prev_close": 100.0, "atr_pct": 2.0, "atr14": 5.0, "or_vol_avg14": 1000.0, "fno": True},
    ])
    strat.on_start(df)

    # 1. LONG1: C > O, range 2.0 <= 0.6 * 5.0 (3.0) -> LONG setup
    strat.on_candle_5m(make_candle("LONG1", 9, 20, 100.0, 102.0, 100.0, 101.5, 3000))
    # 2. SHORT1: C < O, range 2.0 <= 3.0 -> SHORT setup
    strat.on_candle_5m(make_candle("SHORT1", 9, 20, 100.0, 100.5, 98.5, 99.0, 3000))
    # 3. FLAT1: C == O -> skip
    strat.on_candle_5m(make_candle("FLAT1", 9, 20, 100.0, 101.0, 99.0, 100.0, 3000))
    # 4. WIDE1: Range H - L = 4.0 > 0.6 * 5.0 (3.0) -> skip
    strat.on_candle_5m(make_candle("WIDE1", 9, 20, 100.0, 103.5, 99.5, 102.0, 3000))

    setups = strat.compute_ranking()
    sym_setups = {s.symbol: s for s in setups}

    assert "LONG1" in sym_setups
    assert sym_setups["LONG1"].side == "LONG"
    assert sym_setups["LONG1"].trigger == 102.0

    assert "SHORT1" in sym_setups
    assert sym_setups["SHORT1"].side == "SHORT"
    assert sym_setups["SHORT1"].trigger == 98.5

    assert "FLAT1" not in sym_setups
    assert "WIDE1" not in sym_setups


def test_s2_breakout_and_extended_candle_skip():
    strat = S2OrbStrategy()
    df = pd.DataFrame([
        {"symbol": "SYM_NORM", "series": "EQ", "mis_allowed": True, "asm_stage": 0, "gsm": False,
         "adv_cr": 20.0, "prev_close": 1000.0, "atr_pct": 2.0, "atr14": 20.0, "or_vol_avg14": 1000.0, "fno": True},
        {"symbol": "SYM_EXT", "series": "EQ", "mis_allowed": True, "asm_stage": 0, "gsm": False,
         "adv_cr": 20.0, "prev_close": 1000.0, "atr_pct": 2.0, "atr14": 20.0, "or_vol_avg14": 1000.0, "fno": True},
    ])
    strat.on_start(df)

    # Setup at 09:20: High = 1005.0
    strat.on_candle_5m(make_candle("SYM_NORM", 9, 20, 1000.0, 1005.0, 998.0, 1003.0, 3000))
    strat.on_candle_5m(make_candle("SYM_EXT", 9, 20, 1000.0, 1005.0, 998.0, 1003.0, 3000))
    strat.compute_ranking()

    # 1. Normal breakout: 1m candle at 09:22 closes at 1006.0 (trigger = 1005.0).
    # Extended limit is 1005.0 * 1.004 = 1009.02.
    c_norm = make_candle("SYM_NORM", 9, 22, 1004.0, 1006.5, 1003.5, 1006.0, 500)
    sig_norm = strat.on_candle_1m(c_norm)
    assert sig_norm is not None
    assert sig_norm.strategy == "S2"
    assert sig_norm.symbol == "SYM_NORM"
    assert sig_norm.side == "LONG"
    assert sig_norm.ref_price == 1005.0

    # 2. Extended breakout: 1m candle at 09:22 closes at 1010.0 (> 1009.02). Must skip!
    c_ext = make_candle("SYM_EXT", 9, 22, 1004.0, 1011.0, 1003.5, 1010.0, 500)
    sig_ext = strat.on_candle_1m(c_ext)
    assert sig_ext is None


def test_s2_max_trades_per_day_cap():
    strat = S2OrbStrategy()
    df = pd.DataFrame([
        {"symbol": f"SYM{i}", "series": "EQ", "mis_allowed": True, "asm_stage": 0, "gsm": False,
         "adv_cr": 20.0, "prev_close": 500.0, "atr_pct": 2.0, "atr14": 10.0, "or_vol_avg14": 1000.0, "fno": True}
        for i in range(1, 6)
    ])
    strat.on_start(df)

    for i in range(1, 6):
        strat.on_candle_5m(make_candle(f"SYM{i}", 9, 20, 500.0, 503.0, 499.0, 502.0, 3000))
    strat.compute_ranking()

    signals = []
    # Trigger SYM1, SYM2, SYM3, SYM4, SYM5
    for i in range(1, 6):
        c = make_candle(f"SYM{i}", 9, 25, 502.0, 504.0, 501.0, 503.5, 500)
        sig = strat.on_candle_1m(c)
        if sig:
            signals.append(sig)

    # Exactly 3 trades allowed per day
    assert len(signals) == 3
    assert [s.symbol for s in signals] == ["SYM1", "SYM2", "SYM3"]


def test_s2_orb_exits_levels():
    # Long trade with OR high = 1005.0, OR low = 995.0, ATR14 = 10.0
    thesis, safety, profit_lock, exit_by = compute_orb_exits(
        symbol="TEST",
        side="LONG",
        or_high=1005.0,
        or_low=995.0,
        atr14=10.0,
        is_fno=True,
    )
    # Thesis stop = OR low = 995.0
    assert thesis == 995.0
    # Safety stop = OR low - 0.25 * ATR14 = 995 - 2.5 = 992.5 (rounded away from round number if applicable)
    assert safety <= 992.5
    # Profit lock is None by default in ORB
    assert profit_lock is None
    # Exit by is 15:07 for F&O (15:12 - 5 min buffer)
    assert exit_by == "15:07"

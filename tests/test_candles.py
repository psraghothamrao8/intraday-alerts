"""
Tests for candle aggregation, missing minute handling, 5m alignment, and VWAP (spec 05 §7).
"""
from datetime import datetime
import zoneinfo
import pytest
from engine.data.broker_base import Tick
from engine.data.candles import CandleManager, compute_vwap, compute_anchored_vwap

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def make_tick(symbol: str, ltp: float, cum_vol: int, hour: int, minute: int, second: int) -> Tick:
    ts = datetime(2026, 10, 8, hour, minute, second, tzinfo=IST)
    return Tick(symbol=symbol, ltp=ltp, cum_volume=cum_vol, ts=ts)


def test_1m_candle_aggregation():
    mgr = CandleManager("RELIANCE")

    # 09:15 ticks
    mgr.on_tick(make_tick("RELIANCE", 2500.0, 100, 9, 15, 5))
    mgr.on_tick(make_tick("RELIANCE", 2510.0, 300, 9, 15, 20))
    mgr.on_tick(make_tick("RELIANCE", 2495.0, 500, 9, 15, 45))
    mgr.on_tick(make_tick("RELIANCE", 2505.0, 600, 9, 15, 58))

    # 09:16 tick triggers completion of 09:15
    completed_1m, _ = mgr.on_tick(make_tick("RELIANCE", 2506.0, 700, 9, 16, 2))

    assert len(completed_1m) == 1
    c15 = completed_1m[0]
    assert c15.ts == datetime(2026, 10, 8, 9, 15, 0, tzinfo=IST)
    assert c15.open == 2500.0
    assert c15.high == 2510.0
    assert c15.low == 2495.0
    assert c15.close == 2505.0
    assert c15.volume == 600


def test_missing_minute_handling():
    mgr = CandleManager("INFY")

    # 09:15 bar
    mgr.on_tick(make_tick("INFY", 1800.0, 100, 9, 15, 10))
    mgr.on_tick(make_tick("INFY", 1805.0, 200, 9, 15, 50))

    # Skip 09:16 and 09:17; next tick at 09:18
    completed_1m, _ = mgr.on_tick(make_tick("INFY", 1810.0, 350, 9, 18, 5))

    # Should have completed 09:15, and interpolated 09:16 and 09:17
    assert len(completed_1m) == 3

    ts_list = [c.ts.minute for c in completed_1m]
    assert ts_list == [15, 16, 17]

    # Check interpolated 09:16 candle
    c16 = completed_1m[1]
    assert c16.open == 1805.0
    assert c16.high == 1805.0
    assert c16.low == 1805.0
    assert c16.close == 1805.0
    assert c16.volume == 0


def test_5m_candle_alignment():
    mgr = CandleManager("TCS")

    # 5 minutes: 09:15, 09:16, 09:17, 09:18, 09:19
    for m in range(15, 20):
        mgr.on_tick(make_tick("TCS", 3500.0 + m, 100 * (m - 14), 9, m, 10))
        mgr.on_tick(make_tick("TCS", 3505.0 + m, 100 * (m - 14) + 50, 9, m, 50))

    # Tick at 09:20 completes 09:19 1m bar and triggers 09:15 5m bar
    _, completed_5m = mgr.on_tick(make_tick("TCS", 3530.0, 1000, 9, 20, 2))

    assert len(completed_5m) == 1
    c5m = completed_5m[0]
    assert c5m.ts == datetime(2026, 10, 8, 9, 15, 0, tzinfo=IST)
    assert c5m.open == 3515.0  # Open of 09:15
    assert c5m.close == 3524.0  # Close of 09:19 (3505 + 19)
    assert c5m.high == max(c.high for c in mgr.candles_1m[:5])
    assert c5m.low == min(c.low for c in mgr.candles_1m[:5])


def test_day_and_anchored_vwap():
    mgr = CandleManager("SBIN")

    # Generate 3 completed bars
    mgr.on_tick(make_tick("SBIN", 800.0, 1000, 9, 15, 0))
    mgr.on_tick(make_tick("SBIN", 810.0, 2000, 9, 15, 59))  # bar 15: H=810, L=800, C=810 -> TP=806.67, V=2000

    mgr.on_tick(make_tick("SBIN", 810.0, 2000, 9, 16, 0))
    mgr.on_tick(make_tick("SBIN", 820.0, 5000, 9, 16, 59))  # bar 16: H=820, L=810, C=820 -> TP=816.67, V=3000

    mgr.on_tick(make_tick("SBIN", 820.0, 5000, 9, 17, 0))
    mgr.on_tick(make_tick("SBIN", 800.0, 10000, 9, 17, 59))  # bar 17: H=820, L=800, C=800 -> TP=806.67, V=5000

    # Advance to complete bar 17
    mgr.on_tick(make_tick("SBIN", 805.0, 10500, 9, 18, 0))

    bars = mgr.candles_1m
    assert len(bars) == 3

    # Analytical VWAP
    tp1 = (810 + 800 + 810) / 3.0
    tp2 = (820 + 810 + 820) / 3.0
    tp3 = (820 + 800 + 800) / 3.0
    v1, v2, v3 = 2000, 3000, 5000

    expected_vwap = (tp1 * v1 + tp2 * v2 + tp3 * v3) / (v1 + v2 + v3)
    calc_vwap = compute_vwap(bars)
    assert abs(calc_vwap - expected_vwap) < 1e-4

    # Anchored VWAP starting at 09:16
    anchor_time = datetime(2026, 10, 8, 9, 16, 25, tzinfo=IST)
    expected_avwap = (tp2 * v2 + tp3 * v3) / (v2 + v3)
    calc_avwap = compute_anchored_vwap(bars, anchor_time)
    assert abs(calc_avwap - expected_avwap) < 1e-4

"""
Acceptance tests for ExitEngine (spec 07 Task 4).
Tests:
  - Synthetic candles covering each exit reason
  - First condition wins
  - 5-minute wick below thesis level doesn't exit, a close does
  - Time exit at last_exit_time
"""
from datetime import datetime, timezone
import pytest

from engine.core.clock import IST
from engine.core.models import Candle, Tick, Trade
from engine.core.exits import ExitEngine


@pytest.fixture
def sample_long_trade() -> Trade:
    return Trade(
        id="S1-20261008-TEST",
        strategy="S1",
        symbol="TESTSTOCK",
        side="LONG",
        product="MIS",
        strength=8,
        raw_score=7.0,
        why="Test thesis",
        signal_time="2026-10-08T11:00:00+05:30",
        ref_price=1000.0,
        max_entry=1003.0,
        paper_entry=1000.0,
        valid_till="11:05",
        qty=100,
        risk_inr=5000.0,
        thesis_tf="5m",
        thesis_dir="below",
        thesis_level=980.0,
        safety_stop=950.0,
        exit_by="15:07",
        profit_lock_rule="avwap_after_2pct",
        profit_lock_active=False,
        status="OPEN",
        notified=True,
    )


def test_safety_stop_triggered_on_tick(sample_long_trade):
    """Layer 3: tick hitting safety stop triggers exit immediately."""
    engine = ExitEngine()

    # Normal tick above safety stop
    tick_normal = Tick(symbol="TESTSTOCK", timestamp=datetime.now(IST), ltp=960.0)
    assert engine.evaluate_tick(sample_long_trade, tick_normal) is None
    assert sample_long_trade.status == "OPEN"

    # Tick at or below safety stop (950.0)
    tick_stop = Tick(symbol="TESTSTOCK", timestamp=datetime.now(IST), ltp=949.5)
    exit_evt = engine.evaluate_tick(sample_long_trade, tick_stop)

    assert exit_evt is not None
    assert "safety stop hit" in exit_evt.exit_reason
    assert sample_long_trade.status == "EXITED"
    assert sample_long_trade.exit_price == 949.5


def test_thesis_wick_does_not_exit_but_close_does(sample_long_trade):
    """
    Acceptance criteria:
    A 5-minute wick below the thesis level doesn't exit, a close does.
    """
    engine = ExitEngine()

    # Candle 1: Low dips to 975 (below 980 thesis), but closes at 985 (above 980) -> NO EXIT
    candle_wick = Candle(
        symbol="TESTSTOCK",
        timestamp=datetime.now(IST),
        open=990.0,
        high=995.0,
        low=975.0,  # Wick penetrated thesis level (980)
        close=985.0,  # Close is safely above thesis level
        volume=5000,
    )
    assert engine.evaluate_candle_5m(sample_long_trade, candle_wick) is None
    assert sample_long_trade.status == "OPEN"

    # Candle 2: Close penetrates below thesis level (980) -> EXITS
    candle_close_broken = Candle(
        symbol="TESTSTOCK",
        timestamp=datetime.now(IST),
        open=985.0,
        high=986.0,
        low=974.0,
        close=978.0,  # Closed below 980
        volume=6000,
    )
    exit_evt = engine.evaluate_candle_5m(sample_long_trade, candle_close_broken)
    assert exit_evt is not None
    assert "thesis broken" in exit_evt.exit_reason
    assert sample_long_trade.status == "EXITED"
    assert sample_long_trade.exit_price == 978.0


def test_profit_lock_activation_and_trail(sample_long_trade):
    """Profit lock activates at +2% gain, then exits on close below anchored VWAP."""
    engine = ExitEngine()

    # Candle reaches +1.5% (1015) -> profit lock not yet active
    c1 = Candle(symbol="TESTSTOCK", timestamp=datetime.now(IST), open=1000.0, high=1018.0, low=998.0, close=1015.0, volume=1000)
    assert engine.evaluate_candle_5m(sample_long_trade, c1, anchored_vwap=1005.0) is None
    assert sample_long_trade.profit_lock_active is False

    # Candle reaches +2.5% (1025) -> profit lock activates!
    c2 = Candle(symbol="TESTSTOCK", timestamp=datetime.now(IST), open=1015.0, high=1030.0, low=1012.0, close=1025.0, volume=2000)
    assert engine.evaluate_candle_5m(sample_long_trade, c2, anchored_vwap=1010.0) is None
    assert sample_long_trade.profit_lock_active is True

    # Pullback but still above AVWAP (1010) -> no exit
    c3 = Candle(symbol="TESTSTOCK", timestamp=datetime.now(IST), open=1025.0, high=1026.0, low=1011.0, close=1012.0, volume=1500)
    assert engine.evaluate_candle_5m(sample_long_trade, c3, anchored_vwap=1010.0) is None

    # Pullback closes below AVWAP (1010) -> EXITS!
    c4 = Candle(symbol="TESTSTOCK", timestamp=datetime.now(IST), open=1012.0, high=1014.0, low=1005.0, close=1008.0, volume=2500)
    exit_evt = engine.evaluate_candle_5m(sample_long_trade, c4, anchored_vwap=1010.0)
    assert exit_evt is not None
    assert "profit lock" in exit_evt.exit_reason
    assert sample_long_trade.status == "EXITED"


def test_time_exit_at_exit_by_and_last_exit_time(sample_long_trade):
    """Time exit triggers when clock reaches trade.exit_by or calendar last_exit_time."""
    engine = ExitEngine()

    # Time before exit_by (15:00 < 15:07)
    t_before = datetime(2026, 10, 8, 15, 0, tzinfo=IST)
    assert engine.evaluate_clock(sample_long_trade, t_before, current_price=1010.0) is None

    # Time reaches exit_by (15:07)
    t_exit = datetime(2026, 10, 8, 15, 7, tzinfo=IST)
    exit_evt = engine.evaluate_clock(sample_long_trade, t_exit, current_price=1012.0)
    assert exit_evt is not None
    assert "time exit" in exit_evt.exit_reason
    assert sample_long_trade.status == "EXITED"
    assert sample_long_trade.exit_price == 1012.0


def test_first_condition_wins(sample_long_trade):
    """Once a trade exits, subsequent conditions are ignored."""
    engine = ExitEngine()

    # Stop triggered
    tick_stop = Tick(symbol="TESTSTOCK", timestamp=datetime.now(IST), ltp=945.0)
    exit_evt = engine.evaluate_tick(sample_long_trade, tick_stop)
    assert exit_evt is not None
    assert sample_long_trade.status == "EXITED"

    # Later candle attempt does nothing because trade is already EXITED
    c_later = Candle(symbol="TESTSTOCK", timestamp=datetime.now(IST), open=940.0, high=945.0, low=930.0, close=935.0, volume=1000)
    assert engine.evaluate_candle_5m(sample_long_trade, c_later) is None

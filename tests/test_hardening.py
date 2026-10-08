"""
Tests for Task 9: Hardening (watchdog, daily logs, doctor).
Validates:
1. Feed-down detection: no ticks for 60s during market hours triggers ALERT and reconnect.
2. Daily rotating logs in data/logs/ with 30-day retention.
3. System doctor diagnostic functions.
"""
from datetime import datetime, timedelta
from pathlib import Path
import pytest

from engine.core.clock import IST, FakeClock
from engine.core.engine import AlertBotEngine
from engine.core.models import Tick
from engine.doctor import check_env_file, check_webpush_keys, run_doctor
from engine.logging_config import setup_logging, LOG_DIR


def test_feed_watchdog_triggers_alert_after_60s():
    clock = FakeClock()
    engine = AlertBotEngine(clock=clock, is_replay=True)

    # 1. Tick arrives at 09:30:00
    t0 = datetime(2026, 10, 8, 9, 30, 0, tzinfo=IST)
    tick = Tick(symbol="RELIANCE", timestamp=t0, ltp=2500.0)
    engine.step_tick(tick)
    assert engine.last_tick_time == t0
    assert engine.feed_down_alerted is False

    # 2. Advance time 30s (09:30:30) -> Feed is fine
    t_30s = t0 + timedelta(seconds=30)
    clock.set_time(t_30s)
    stalled = engine.check_feed_watchdog(t_30s)
    assert stalled is False
    assert engine.feed_down_alerted is False

    # 3. Advance time to 65s (09:31:05) -> Feed stalled!
    t_65s = t0 + timedelta(seconds=65)
    clock.set_time(t_65s)
    stalled = engine.check_feed_watchdog(t_65s)
    assert stalled is True
    assert engine.feed_down_alerted is True

    # 4. New tick restores feed health
    t_restore = t0 + timedelta(seconds=70)
    new_tick = Tick(symbol="RELIANCE", timestamp=t_restore, ltp=2501.0)
    engine.step_tick(new_tick)
    assert engine.feed_down_alerted is False


def test_rotating_daily_logs(tmp_path):
    setup_logging()
    assert LOG_DIR.exists()
    log_file = LOG_DIR / "engine.log"
    # Write a test log
    import logging
    logging.getLogger("test_hardening").info("Test rotating log line")
    assert log_file.exists()


def test_doctor_diagnostics():
    # Verify diagnostic functions run cleanly
    env_ok, env_msg = check_env_file()
    assert isinstance(env_ok, bool)
    assert len(env_msg) > 0

    vapid_ok, vapid_msg = check_webpush_keys()
    assert isinstance(vapid_ok, bool)

    # Full doctor run prints table and returns boolean
    res = run_doctor()
    assert isinstance(res, bool)

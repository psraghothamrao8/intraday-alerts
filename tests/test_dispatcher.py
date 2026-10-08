"""
Tests for notification dispatcher (spec 04 §4).
Verifies:
1. Sending the same ENTRY twice delivers once (exactly-once).
2. HTTP 410 marks device inactive and triggers Telegram ALERT.
"""
import json
from unittest.mock import patch, MagicMock
import pytest
from engine.core.state import init_db, add_device, get_active_devices
from engine.notify.dispatcher import NotificationDispatcher


@pytest.fixture
def test_db_conn(tmp_path):
    db_file = tmp_path / "test_state.db"
    conn = init_db(db_file)
    return conn


@pytest.fixture
def sample_trade():
    return {
        "id": "S1-20261008-KPITTECH",
        "symbol": "KPITTECH",
        "side": "LONG",
        "product": "MIS",
        "strength": 8,
        "max_entry": 1452.00,
        "valid_till": "11:45",
        "exit_by": "15:07",
        "thesis": {"tf": "5m", "dir": "below", "level": 1428.50},
        "safety_stop": 1404.00,
        "qty": 41,
        "risk_inr": 1968,
        "why": "Q2 results: Rev +28% · PAT +61% · margin +310bps (consol.)",
        "status": "OPEN",
    }


def test_exactly_once_delivery(test_db_conn, sample_trade):
    # Add active device
    sub = {
        "endpoint": "https://push.example.com/sub/123",
        "keys": {"p256dh": "dummy_p256dh", "auth": "dummy_auth"}
    }
    add_device("Pixel 8", json.dumps(sub), conn=test_db_conn)
    assert len(get_active_devices(test_db_conn)) == 1

    dispatcher = NotificationDispatcher(conn=test_db_conn)

    with patch("engine.notify.dispatcher.send_webpush", return_value=201) as mock_push, \
         patch("engine.notify.dispatcher.send_telegram", return_value=True) as mock_tg:

        # First dispatch
        res1 = dispatcher.dispatch_trade_entry(sample_trade)
        assert res1 is True
        assert mock_push.call_count == 1

        # Second dispatch of the exact same trade
        res2 = dispatcher.dispatch_trade_entry(sample_trade)
        assert res2 is False
        # Delivery must NOT be called again
        assert mock_push.call_count == 1


def test_http_410_marks_inactive_and_alerts_telegram(test_db_conn, sample_trade):
    endpoint = "https://push.example.com/sub/expired410"
    sub = {
        "endpoint": endpoint,
        "keys": {"p256dh": "dummy_p256dh", "auth": "dummy_auth"}
    }
    add_device("Expired Phone", json.dumps(sub), conn=test_db_conn)
    assert len(get_active_devices(test_db_conn)) == 1

    dispatcher = NotificationDispatcher(conn=test_db_conn)

    with patch("engine.notify.dispatcher.send_webpush", return_value=410) as mock_push, \
         patch("engine.notify.dispatcher.send_telegram") as mock_tg:

        res = dispatcher.dispatch_trade_entry(sample_trade)
        assert res is True
        assert mock_push.call_count == 1

        # 1. Device marked inactive
        active_devices = get_active_devices(test_db_conn)
        assert len(active_devices) == 0

        # 2. Telegram alert triggered
        assert mock_tg.called
        # Check call arguments
        title_arg = mock_tg.call_args[1].get("title") or mock_tg.call_args[0][0]
        assert "expired" in title_arg.lower()

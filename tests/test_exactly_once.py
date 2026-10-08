"""
Acceptance test for kill-and-restart mid-trade (spec 07 Task 4).
Verifies:
  - Kill and restart engine mid-trade in replay
  - No duplicate ENTRY notification
  - EXIT notification still arrives exactly once
"""
import sqlite3
import pytest
from datetime import datetime

from engine.core.clock import IST
from engine.core.models import Candle, Tick, Trade
from engine.core.state import init_db, save_trade, get_trade, get_open_trades, update_trade
from engine.notify.dispatcher import NotificationDispatcher
from engine.core.exits import ExitEngine
from engine.core.risk import RiskManager


def test_kill_and_restart_mid_trade(tmp_path):
    """
    Simulates:
      1. Engine starts, takes a trade, sends ENTRY notification.
      2. Engine is killed (process exits).
      3. Engine restarts from the same SQLite DB.
      4. Verifies no duplicate ENTRY is sent.
      5. Trade exits on safety stop, EXIT notification arrives.
      6. Verified exactly one ENTRY and one EXIT exist in DB.
    """
    db_file = tmp_path / "test_state.db"
    conn = init_db(db_file)

    notif_log = tmp_path / "notifs.jsonl"
    dispatcher_1 = NotificationDispatcher(conn=conn, notify_file=str(notif_log))
    exit_engine_1 = ExitEngine()

    trade_id = "S1-20261008-KILLTEST"
    trade = Trade(
        id=trade_id,
        strategy="S1",
        symbol="KILLTEST",
        side="LONG",
        product="MIS",
        strength=8,
        raw_score=7.0,
        why="Kill and restart test",
        signal_time="2026-10-08T11:00:00+05:30",
        ref_price=500.0,
        max_entry=502.0,
        paper_entry=500.0,
        valid_till="11:05",
        qty=50,
        risk_inr=2500.0,
        thesis_tf="5m",
        thesis_dir="below",
        thesis_level=490.0,
        safety_stop=475.0,
        exit_by="15:07",
        profit_lock_rule="avwap_after_2pct",
        profit_lock_active=False,
        status="OPEN",
        notified=False,
    )

    # 1. First run: Open trade and dispatch ENTRY
    save_trade(trade.to_dict(), conn)
    entry_sent = dispatcher_1.dispatch_trade_entry(trade.to_dict())
    assert entry_sent is True
    trade.notified = True
    update_trade(trade_id, {"notified": 1}, conn)

    # -------------------------------------------------------------
    # 2. KILL ENGINE (close conn, destroy instances)
    # -------------------------------------------------------------
    conn.close()
    del dispatcher_1
    del exit_engine_1

    # -------------------------------------------------------------
    # 3. RESTART ENGINE from disk
    # -------------------------------------------------------------
    conn_2 = sqlite3.connect(db_file)
    dispatcher_2 = NotificationDispatcher(conn=conn_2, notify_file=str(notif_log))
    exit_engine_2 = ExitEngine()

    # Engine reloads open trades from SQLite
    open_trades_raw = get_open_trades(conn_2)
    assert len(open_trades_raw) == 1
    reloaded_trade = Trade.from_dict(open_trades_raw[0])
    assert reloaded_trade.id == trade_id
    assert reloaded_trade.status == "OPEN"
    assert reloaded_trade.notified is True

    # Attempt to dispatch ENTRY again (e.g. from poller replay or dedupe check)
    dup_entry_sent = dispatcher_2.dispatch_trade_entry(reloaded_trade.to_dict())
    assert dup_entry_sent is False  # BLOCKED! No duplicate ENTRY.

    # 4. Market tick hits safety stop (470.0 < 475.0)
    stop_tick = Tick(symbol="KILLTEST", timestamp=datetime.now(IST), ltp=470.0)
    exit_evt = exit_engine_2.evaluate_tick(reloaded_trade, stop_tick)
    assert exit_evt is not None
    assert reloaded_trade.status == "EXITED"

    # Dispatch EXIT
    exit_sent = dispatcher_2.dispatch_trade_exit(reloaded_trade.to_dict())
    assert exit_sent is True
    update_trade(trade_id, {
        "status": "EXITED",
        "exit_price": reloaded_trade.exit_price,
        "exit_time": reloaded_trade.exit_time,
        "exit_reason": reloaded_trade.exit_reason,
        "paper_net_pct": reloaded_trade.paper_net_pct,
    }, conn_2)

    # Attempt to dispatch EXIT again -> blocked
    dup_exit_sent = dispatcher_2.dispatch_trade_exit(reloaded_trade.to_dict())
    assert dup_exit_sent is False

    # 5. Verify database records
    cursor = conn_2.cursor()
    cursor.execute("SELECT id, kind FROM notifications WHERE trade_id = ? ORDER BY created_at", (trade_id,))
    notifs = cursor.fetchall()

    # Exactly 2 notifications: one ENTRY, one EXIT
    assert len(notifs) == 2
    assert notifs[0][1] == "ENTRY"
    assert notifs[1][1] == "EXIT"

    final_trade = get_trade(trade_id, conn_2)
    assert final_trade["status"] == "EXITED"

    conn_2.close()

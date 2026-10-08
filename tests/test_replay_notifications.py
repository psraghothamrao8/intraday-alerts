"""
Acceptance test for engine replay notification pairs (spec 07 Task 4).
Verifies:
  - Replay produces an ENTRY and EXIT pair for every notified trade, and nothing else.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import pytest
import pandas as pd

from engine.core.clock import FakeClock, IST
from engine.core.engine import AlertBotEngine
from engine.core.models import Candle
from engine.core.state import init_db, save_filing
from engine.llm.schemas import ResultsExtraction, Statement, Period


@pytest.mark.asyncio
async def test_replay_produces_entry_and_exit_pairs(tmp_path):
    """
    Test that replaying a day with saved data produces an ENTRY and EXIT pair
    for every notified trade, and nothing else.
    """
    db_file = tmp_path / "test_replay.db"
    conn = init_db(db_file)

    notify_file = tmp_path / "replay_notifs.jsonl"
    replay_date = date(2026, 10, 8)
    fake_clock = FakeClock(datetime(2026, 10, 8, 9, 15, tzinfo=IST))

    engine = AlertBotEngine(clock=fake_clock, notify_file=str(notify_file), is_replay=True)
    engine.db_conn = conn
    engine.dispatcher.conn = conn

    # Setup universe mock in engine
    engine.universe_df = pd.DataFrame([{
        "symbol": "BULLSTOCK",
        "isin": "INE123456789",
        "bse_code": "500123",
        "series": "EQ",
        "fno": False,
        "asm_stage": 0,
        "gsm": False,
        "mis_allowed": True,
        "short_allowed": True,
        "prev_close": 500.0,
        "atr14": 15.0,
        "atr_pct": 3.0,
        "adv_cr": 25.0,
        "mcap_cr": 5000.0,
        "deliv_pct_20d": 45.0,
        "or_vol_avg14": 10000.0,
        "tick_size": 0.05,
    }])
    engine.universe_map = {row["symbol"]: row.to_dict() for _, row in engine.universe_df.iterrows()}
    for s in engine.strategies:
        s.on_start(engine.universe_df)

    # 1. Create a bullish filing with pre-extracted ResultsExtraction (score >= 6 -> Signal)
    stmt = Statement(
        current_qtr=Period(revenue_ops=1200.0, net_profit=200.0, profit_before_tax=250.0, total_expenses=950.0, depreciation=30.0, finance_costs=20.0),
        previous_qtr=Period(revenue_ops=1050.0, net_profit=160.0, profit_before_tax=200.0),
        year_ago_qtr=Period(revenue_ops=1000.0, net_profit=140.0, profit_before_tax=180.0, total_expenses=820.0, depreciation=25.0, finance_costs=15.0),
    )
    ext = ResultsExtraction(
        is_financial_results=True,
        period_end="2026-09-30",
        unit="crores",
        consolidated=stmt,
    )

    filing_id = "BSE:TEST_BULL_01"
    filing_record = {
        "id": filing_id,
        "exchange": "BSE",
        "symbol": "BULLSTOCK",
        "isin": "INE123456789",
        "bse_code": "500123",
        "company": "Bullish Company Ltd",
        "category": "Results",
        "subcategory": "Financial Results",
        "subject": "Financial Results for Q2 FY27",
        "disseminated_at": "2026-10-08T10:00:00+05:30",
        "pdf_url": "https://example.com/test.pdf",
        "pdf_sha256": "abcdef123456",
        "trigger_group": "results",
        "status": "pending",
        "status_reason": "",
        "processed_at": "2026-10-08T10:00:05+05:30",
        "llm_model": "claude-opus-5-5",
        "llm_ms": 1200,
        "extraction_json": ext.model_dump_json(),
    }
    save_filing(filing_record, conn)

    # 2. Step filing into engine (generates ENTRY signal and dispatches ENTRY notification)
    trade = await engine.step_filing(filing_record, current_price=500.0)
    assert trade is not None
    assert trade.status == "OPEN"
    assert trade.notified is True
    assert trade.symbol == "BULLSTOCK"

    # 3. Step candles forward:
    # 5m candle that closes below thesis level (thesis level is ref_price - 0.1*atr14 = 500 - 1.5 = 498.5)
    t_candle = datetime(2026, 10, 8, 10, 15, tzinfo=IST)
    c_exit = Candle(
        symbol="BULLSTOCK",
        timestamp=t_candle,
        open=499.0,
        high=500.0,
        low=495.0,
        close=496.0,  # Below 498.5 -> thesis stop triggers!
        volume=10000,
    )
    exits = engine.step_candle_5m(c_exit)
    assert len(exits) == 1
    assert exits[0].trade_id == trade.id

    # 4. Read notifications file and verify exact contents
    assert notify_file.exists()
    lines = [json.loads(line) for line in notify_file.read_text(encoding="utf-8").strip().split("\n")]

    # Verification: Exactly one ENTRY and one EXIT pair for every notified trade, and nothing else
    assert len(lines) == 2, f"Expected 2 notifications, got {len(lines)}"

    notif_entry = lines[0]
    notif_exit = lines[1]

    assert notif_entry["kind"] == "ENTRY"
    assert notif_entry["trade_id"] == trade.id

    assert notif_exit["kind"] == "EXIT"
    assert notif_exit["trade_id"] == trade.id

    assert notif_entry["notif_id"] == f"{trade.id}:ENTRY"
    assert notif_exit["notif_id"] == f"{trade.id}:EXIT"

    conn.close()

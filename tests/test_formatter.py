"""
Tests for notification text formatter (spec 04 §3).
Ensures exact match with spec examples, Indian currency grouping, and null line omission.
"""
from engine.notify.formatter import format_entry, format_exit, format_inr, format_indian_number


def test_indian_number_formatting():
    assert format_indian_number(1452.00, decimals=2) == "1,452.00"
    assert format_indian_number(123456.50, decimals=2) == "1,23,456.50"
    assert format_indian_number(1968, decimals=0) == "1,968"
    assert format_indian_number(702.10, decimals=2) == "702.10"
    assert format_indian_number(10000000, decimals=0) == "1,00,00,000"


def test_entry_long_intraday():
    trade = {
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
        "why": "Q2 results: Rev +28% · PAT +61% · margin +310bps (consol.)"
    }
    title, body = format_entry(trade)
    assert title == "🟢 BUY KPITTECH · 8/10"
    expected_body = (
        "Buy ≤ ₹1,452.00 now · valid till 11:45\n"
        "Sell: by 15:07\n"
        "Stop: only if a 5-min candle closes below ₹1,428.50\n"
        "Safety SL order ₹1,404.00 · Qty 41 (risk ₹1,968)\n"
        "Q2 results: Rev +28% · PAT +61% · margin +310bps (consol.)"
    )
    assert body == expected_body


def test_entry_short_intraday():
    trade = {
        "id": "S2-20261008-HDFCLIFE",
        "symbol": "HDFCLIFE",
        "side": "SHORT",
        "product": "MIS",
        "strength": 6,
        "max_entry": 702.10,
        "valid_till": "09:41",
        "exit_by": "15:07",
        "thesis": {"tf": "5m", "dir": "above", "level": 709.40},
        "safety_stop": 713.00,
        "qty": 180,
        "risk_inr": 1962,
        "why": "Stock in play: volume 4.2× normal in first 5 min · gap −1.8%"
    }
    title, body = format_entry(trade)
    assert title == "🔻 SHORT HDFCLIFE · 6/10"
    expected_body = (
        "Sell (intraday) ≥ ₹702.10 now · valid till 09:41\n"
        "Buy back: by 15:07\n"
        "Stop: only if a 5-min candle closes above ₹709.40\n"
        "Safety SL-buy order ₹713.00 · Qty 180 (risk ₹1,962)\n"
        "Stock in play: volume 4.2× normal in first 5 min · gap −1.8%"
    )
    assert body == expected_body


def test_entry_long_delivery_s4():
    trade = {
        "id": "S4-20261008-ABCLTD",
        "symbol": "ABCLTD",
        "side": "LONG",
        "product": "CNC",
        "strength": 7,
        "max_entry": 318.40,
        "valid_till": "1 min",
        "exit_by": "15:25",
        "thesis": None,
        "safety_stop": 315.20,
        "qty": 300,
        "risk_inr": None,
        "why": "Square-off dip: −0.7% in the 15:20 minute · day −3.4% · low delivery"
    }
    title, body = format_entry(trade)
    assert title == "🟢 BUY ABCLTD (delivery) · 7/10"
    expected_body = (
        "Buy as CNC, full cash, ≤ ₹318.40 now · valid 1 min\n"
        "Sell: 15:25 (you'll get a SELL alert)\n"
        "Safety SL order ₹315.20 · Qty 300\n"
        "Square-off dip: −0.7% in the 15:20 minute · day −3.4% · low delivery"
    )
    assert body == expected_body


def test_exit_long():
    trade = {
        "id": "S1-20261008-KPITTECH",
        "symbol": "KPITTECH",
        "side": "LONG",
        "exit_reason": "Idea broken: 5-min close ₹1,426.80 below ₹1,428.50",
        "paper_net_pct": -1.6,
        "paper_pnl_inr": -950,
    }
    title, body = format_exit(trade)
    assert title == "🔴 SELL KPITTECH now"
    expected_body = (
        "Idea broken: 5-min close ₹1,426.80 below ₹1,428.50\n"
        "Paper result: −1.6% (−₹950)\n"
        "Cancel your safety SL order."
    )
    assert body == expected_body


def test_exit_short():
    trade = {
        "id": "S2-20261008-HDFCLIFE",
        "symbol": "HDFCLIFE",
        "side": "SHORT",
        "exit_reason": "Time exit (15:07)",
        "paper_net_pct": 1.9,
        "paper_pnl_inr": 2410,
    }
    title, body = format_exit(trade)
    assert title == "🟢 BUY BACK HDFCLIFE now"
    expected_body = (
        "Time exit (15:07)\n"
        "Paper result: +1.9% (+₹2,410)\n"
        "Cancel your safety SL-buy order."
    )
    assert body == expected_body


def test_null_lines_omitted():
    trade = {
        "id": "T-MINIMAL",
        "symbol": "TATASTEEL",
        "side": "LONG",
        "product": "MIS",
        "strength": 6,
        "max_entry": 150.00,
        "valid_till": None,
        "exit_by": None,
        "thesis": None,
        "safety_stop": None,
        "qty": None,
        "risk_inr": None,
        "why": None,
    }
    title, body = format_entry(trade)
    assert title == "🟢 BUY TATASTEEL · 6/10"
    assert body == "Buy ≤ ₹150.00 now"

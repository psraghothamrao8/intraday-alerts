"""
Notification text formatter.
Generates exact title and body texts per spec 04 §3 with Indian currency formatting.
"""
from typing import Any, Dict, Optional, Tuple
from engine.core.clock import get_clock


def format_indian_number(val: float | int, decimals: int = 2) -> str:
    """
    Format a number with Indian digit grouping (e.g. 1,23,456.50).
    Last 3 digits grouped together, preceding digits grouped by 2.
    """
    if decimals > 0:
        formatted = f"{abs(val):.{decimals}f}"
        integer_part, decimal_part = formatted.split(".")
    else:
        integer_part = str(int(round(abs(val))))
        decimal_part = ""

    if len(integer_part) <= 3:
        grouped = integer_part
    else:
        last3 = integer_part[-3:]
        remaining = integer_part[:-3]
        groups = []
        while remaining:
            groups.append(remaining[-2:])
            remaining = remaining[:-2]
        groups.reverse()
        grouped = ",".join(groups) + "," + last3

    if decimal_part:
        return f"{grouped}.{decimal_part}"
    return grouped


def format_inr(val: float | int | None, decimals: int = 2, show_sign: bool = False) -> str:
    """Format currency in INR with ₹ symbol and Indian grouping."""
    if val is None:
        return ""
    abs_str = format_indian_number(val, decimals=decimals)
    if val < 0:
        return f"−₹{abs_str}"
    elif val > 0 and show_sign:
        return f"+₹{abs_str}"
    return f"₹{abs_str}"


def format_pct(val: float | None, decimals: int = 1, show_sign: bool = True) -> str:
    """Format percentage with Indian sign style (e.g. +1.9%, −1.6%)."""
    if val is None:
        return ""
    abs_str = f"{abs(val):.{decimals}f}"
    if val < 0:
        return f"−{abs_str}%"
    elif val > 0 and show_sign:
        return f"+{abs_str}%"
    return f"{abs_str}%"


def format_entry(trade: Dict[str, Any], simple: bool = False) -> Tuple[str, str]:
    """
    Format an ENTRY notification (title, body) matching spec 04 §3.
    When simple=True, provides an intuitive numbered step-by-step format for beginners.
    """
    symbol = trade.get("symbol", "")
    side = trade.get("side", "LONG").upper()
    product = trade.get("product", "MIS").upper()
    strength = trade.get("strength")
    strength_str = f" · {strength}/10" if strength is not None else ""

    # Title
    if side == "LONG":
        if product == "CNC":
            title = f"🟢 BUY {symbol} (delivery){strength_str}"
        else:
            title = f"🟢 BUY {symbol}{strength_str}"
    else:
        title = f"🔻 SHORT {symbol}{strength_str}"

    if simple:
        # Intuitive step-by-step format
        lines = []
        max_entry = trade.get("max_entry")
        valid_till = trade.get("valid_till")
        qty = trade.get("qty")
        risk_inr = trade.get("risk_inr")

        entry_part = f"≤ {format_inr(max_entry, decimals=2)}" if max_entry is not None else ""
        if side == "SHORT":
            entry_part = f"≥ {format_inr(max_entry, decimals=2)}" if max_entry is not None else ""

        val_part = f"(valid {valid_till})" if valid_till else ""
        qty_part = f"· Qty {qty}" if qty is not None else ""
        if risk_inr is not None:
            qty_part += f" (risk {format_inr(risk_inr, decimals=0)})"

        if product == "CNC":
            lines.append(f"1. Buy CNC {entry_part} {val_part} {qty_part}".strip())
        elif side == "SHORT":
            lines.append(f"1. Sell MIS {entry_part} {val_part} {qty_part}".strip())
        else:
            lines.append(f"1. Buy MIS {entry_part} {val_part} {qty_part}".strip())

        safety_stop = trade.get("safety_stop")
        if safety_stop is not None:
            sl_str = format_inr(safety_stop, decimals=2)
            if side == "SHORT":
                lines.append(f"2. Safety Stop: {sl_str} (put SL-M BUY order in broker now)")
            else:
                lines.append(f"2. Safety Stop: {sl_str} (put SL-M order in broker now)")

        exit_by = trade.get("exit_by")
        thesis = trade.get("thesis")
        if exit_by:
            if thesis and thesis.get("level") is not None:
                lvl_str = format_inr(thesis["level"], decimals=2)
                lines.append(f"3. Exit by {exit_by} (or if 5-min candle breaks {lvl_str})")
            else:
                lines.append(f"3. Exit by {exit_by} (wait for SELL alert)")

        why = trade.get("why")
        if why:
            lines.append(f"Why: {why}")

        body = "\n".join(lines)
        return title, body

    lines = []

    # Line 1: Entry price & validity
    max_entry = trade.get("max_entry")
    valid_till = trade.get("valid_till")
    if max_entry is not None:
        entry_str = format_inr(max_entry, decimals=2)
        if valid_till:
            if "min" in str(valid_till):
                val_phrase = f"now · valid {valid_till}"
            elif str(valid_till).startswith("valid"):
                val_phrase = f"now · {valid_till}"
            else:
                val_phrase = f"now · valid till {valid_till}"
        else:
            val_phrase = "now"

        if product == "CNC":
            lines.append(f"Buy as CNC, full cash, ≤ {entry_str} {val_phrase}")
        elif side == "SHORT":
            lines.append(f"Sell (intraday) ≥ {entry_str} {val_phrase}")
        else:
            lines.append(f"Buy ≤ {entry_str} {val_phrase}")

    # Line 2: Exit-by
    exit_by = trade.get("exit_by")
    if exit_by:
        if product == "CNC":
            lines.append(f"Sell: {exit_by} (you'll get a SELL alert)")
        elif side == "SHORT":
            lines.append(f"Buy back: by {exit_by}")
        else:
            lines.append(f"Sell: by {exit_by}")

    # Line 3: Thesis stop
    thesis = trade.get("thesis")
    if thesis and thesis.get("level") is not None:
        level_str = format_inr(thesis["level"], decimals=2)
        dir_word = thesis.get("dir", "below" if side == "LONG" else "above")
        tf = thesis.get("tf", "5-min")
        if tf == "5m":
            tf = "5-min"
        lines.append(f"Stop: only if a {tf} candle closes {dir_word} {level_str}")

    # Line 4: Safety SL order & qty
    safety_stop = trade.get("safety_stop")
    qty = trade.get("qty")
    risk_inr = trade.get("risk_inr")
    if safety_stop is not None and qty is not None:
        sl_str = format_inr(safety_stop, decimals=2)
        order_name = "Safety SL-buy order" if side == "SHORT" else "Safety SL order"
        if risk_inr is not None:
            risk_str = format_inr(risk_inr, decimals=0)
            lines.append(f"{order_name} {sl_str} · Qty {qty} (risk {risk_str})")
        else:
            lines.append(f"{order_name} {sl_str} · Qty {qty}")

    # Line 5: Why / catalyst description
    why = trade.get("why")
    if why:
        lines.append(why)

    body = "\n".join(lines)
    return title, body


def format_exit(trade: Dict[str, Any], simple: bool = False) -> Tuple[str, str]:
    """
    Format an EXIT notification (title, body) matching spec 04 §3.
    When simple=True, provides an intuitive numbered step-by-step format for beginners.
    """
    symbol = trade.get("symbol", "")
    side = trade.get("side", "LONG").upper()

    # Title
    if side == "SHORT":
        title = f"🟢 BUY BACK {symbol} now"
    else:
        title = f"🔴 SELL {symbol} now"

    lines = []

    exit_reason = trade.get("exit_reason")
    paper_net_pct = trade.get("paper_net_pct")
    paper_entry = trade.get("paper_entry")
    exit_price = trade.get("exit_price")
    qty = trade.get("qty", 1)

    # Compute paper P&L
    paper_pnl_inr = trade.get("paper_pnl_inr")
    if paper_pnl_inr is None and paper_entry is not None and exit_price is not None:
        if side == "SHORT":
            paper_pnl_inr = (paper_entry - exit_price) * qty
        else:
            paper_pnl_inr = (exit_price - paper_entry) * qty

    pct_str = format_pct(paper_net_pct, decimals=1, show_sign=True) if paper_net_pct is not None else ""
    pnl_inr_str = format_inr(paper_pnl_inr, decimals=0, show_sign=True) if paper_pnl_inr is not None else ""

    if simple:
        if exit_reason:
            lines.append(f"1. Reason: {exit_reason}")
        if pct_str:
            res_str = f"{pct_str} ({pnl_inr_str})" if pnl_inr_str else pct_str
            lines.append(f"2. Result: {res_str}")
        if side == "SHORT":
            lines.append("3. Action: Buy back in broker & cancel safety SL-buy order.")
        else:
            lines.append("3. Action: Sell in broker & cancel safety SL order.")
        body = "\n".join(lines)
        return title, body

    # Line 1: Exit reason
    if exit_reason:
        lines.append(exit_reason)

    # Line 2: Paper result
    if paper_net_pct is not None:
        if paper_pnl_inr is not None:
            lines.append(f"Paper result: {pct_str} ({pnl_inr_str})")
        else:
            lines.append(f"Paper result: {pct_str}")

    # Line 3: Reminder to cancel broker SL order
    if side == "SHORT":
        lines.append("Cancel your safety SL-buy order.")
    else:
        lines.append("Cancel your safety SL order.")

    body = "\n".join(lines)
    return title, body


def build_push_payload(
    kind: str,
    item_id: str,
    title: str,
    body: str,
    url: Optional[str] = None,
    sticky: bool = True,
    ts: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build Web Push JSON payload conforming to spec 04 §3.
    """
    if ts is None:
        ts = get_clock().now().isoformat()
    if url is None:
        url = f"./#t={item_id}" if not item_id.startswith("alert:") else "./"
    tag = f"{item_id}:{kind}"

    return {
        "v": 1,
        "kind": kind,
        "id": item_id,
        "title": title,
        "body": body,
        "tag": tag,
        "url": url,
        "sticky": sticky,
        "ts": ts
    }

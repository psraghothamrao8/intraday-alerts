"""
Snapshot builder for published state.
Implements spec 04 §7.4 and envelope in §7.1.
"""
from typing import Any, Dict, List, Optional, Tuple
from engine.config import get_settings
from engine.core.clock import get_clock
from engine.core.calendar import next_trading_day
from engine.core.state import (
    get_connection,
    get_today_trades,
    get_history_trades,
    get_recent_events,
)
from engine.publish.crypto import encrypt_payload

STRATEGY_NAMES = {
    "S1": "Results-Hour Reader",
    "S2": "Stocks-in-play ORB",
    "S3": "Filing Flash",
    "S4": "Square-off crush",
}


def compute_scoreboard(history_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute scoreboard stats per strategy."""
    settings = get_settings()
    scoreboard = []

    for strat_id, strat_name in STRATEGY_NAMES.items():
        strat_trades = [t for t in history_trades if t.get("strategy") == strat_id]
        n_all = len(strat_trades)

        # 30-day window
        # In history_trades, trades are already within last 30 days or recent
        trades_30d = strat_trades[:30]
        n_30d = len(trades_30d)

        wins_30d = [t for t in trades_30d if (t.get("paper_net_pct") or 0) > 0]
        win_rate_30d = round(len(wins_30d) / n_30d, 2) if n_30d > 0 else 0.0

        net_pcts_30d = [(t.get("paper_net_pct") or 0.0) for t in trades_30d]
        avg_net_pct_30d = round(sum(net_pcts_30d) / n_30d, 2) if n_30d > 0 else 0.0
        sum_net_pct_30d = round(sum(net_pcts_30d), 2)

        net_pcts_all = [(t.get("paper_net_pct") or 0.0) for t in strat_trades]
        avg_net_pct_all = round(sum(net_pcts_all) / n_all, 2) if n_all > 0 else 0.0

        # Last 10 streak
        last10_trades = strat_trades[:10]
        last10 = "".join(["W" if (t.get("paper_net_pct") or 0) > 0 else "L" for t in last10_trades])

        scoreboard.append({
            "strategy": strat_id,
            "name": strat_name,
            "mode": settings.mode,
            "n_30d": n_30d,
            "win_rate_30d": win_rate_30d,
            "avg_net_pct_30d": avg_net_pct_30d,
            "sum_net_pct_30d": sum_net_pct_30d,
            "n_all": n_all,
            "avg_net_pct_all": avg_net_pct_all,
            "last10": last10,
        })

    return scoreboard


def build_snapshot(
    health_info: Optional[Dict[str, Any]] = None,
    engine_status: str = "running",
    passphrase: Optional[str] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Build plaintext state dictionary and encrypted envelope.
    Returns (envelope, decrypted_state).
    """
    settings = get_settings()
    clock = get_clock()
    now_dt = clock.now()
    now_iso = now_dt.isoformat()
    today_str = now_dt.date().isoformat()
    next_day_str = next_trading_day(now_dt.date()).isoformat()

    conn = get_connection()
    today_trades = get_today_trades(today_str, conn)
    history_trades = get_history_trades(30, conn)

    # Calculate today PnL
    today_net_pcts = [t.get("paper_net_pct") for t in today_trades if t.get("paper_net_pct") is not None]
    today_pnl_pct = round(sum(today_net_pcts), 2) if today_net_pcts else 0.0

    recent_events = get_recent_events(limit=5, conn=conn)
    last_err = next((e["message"] for e in recent_events if e["level"] in ("ERROR", "CRITICAL")), None)

    health = {
        "feed": health_info.get("feed", "ok") if health_info else "ok",
        "bse_last_poll": health_info.get("bse_last_poll", now_dt.strftime("%H:%M:%S")) if health_info else now_dt.strftime("%H:%M:%S"),
        "nse_last_poll": health_info.get("nse_last_poll", now_dt.strftime("%H:%M:%S")) if health_info else now_dt.strftime("%H:%M:%S"),
        "llm_errors_today": health_info.get("llm_errors_today", 0) if health_info else 0,
        "last_error": last_err,
    }

    scoreboard = compute_scoreboard(history_trades)

    decrypted_state = {
        "generated_at": now_iso,
        "mode": settings.mode,
        "engine_version": "0.3.0",
        "health": health,
        "today": {
            "date": today_str,
            "paper_pnl_pct": today_pnl_pct,
            "entries": len(today_trades),
            "trades": today_trades,
        },
        "history": history_trades,
        "scoreboard": scoreboard,
        "research": {
            "S4": {
                "sessions": 0,
                "promoted": False,
                "top_groups": [],
            }
        },
    }

    # Encrypt
    passphrase = passphrase or settings.DATA_PASSPHRASE
    salt_b64, iv_b64, ct_b64 = encrypt_payload(decrypted_state, passphrase)

    envelope = {
        "v": 1,
        "updated_at": now_iso,
        "heartbeat_at": now_iso,
        "engine_status": engine_status,
        "next_trading_day": next_day_str,
        "salt": salt_b64,
        "iv": iv_b64,
        "ct": ct_b64,
    }

    return envelope, decrypted_state

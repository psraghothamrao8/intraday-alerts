"""
State database access and DAO operations.
Uses SQLite in WAL mode for robust, concurrent, restart-resilient state.
"""
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
from engine.core.clock import get_clock


DEFAULT_DB_PATH = Path("data/state.db")


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open or create a SQLite database connection with WAL mode and row factory."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Initialize database tables per spec 05 §10 and 04 §4."""
    conn = get_connection(db_path)
    with conn:
        # 1. filings
        conn.execute("""
            CREATE TABLE IF NOT EXISTS filings (
                id TEXT PRIMARY KEY,
                exchange TEXT,
                symbol TEXT,
                isin TEXT,
                bse_code TEXT,
                company TEXT,
                category TEXT,
                subcategory TEXT,
                subject TEXT,
                disseminated_at TEXT,
                pdf_url TEXT,
                pdf_sha256 TEXT,
                trigger_group TEXT,
                status TEXT,
                status_reason TEXT,
                processed_at TEXT,
                llm_model TEXT,
                llm_ms INTEGER,
                extraction_json TEXT
            );
        """)

        # 2. fundamentals
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                symbol TEXT,
                period_end TEXT,
                basis TEXT,
                unit TEXT,
                json TEXT,
                source_url TEXT,
                extracted_at TEXT,
                PRIMARY KEY (symbol, period_end, basis)
            );
        """)

        # 3. trades
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                strategy TEXT,
                symbol TEXT,
                side TEXT,
                product TEXT,
                strength INTEGER,
                raw_score REAL,
                why TEXT,
                source_url TEXT,
                signal_time TEXT,
                ref_price REAL,
                max_entry REAL,
                valid_till TEXT,
                qty INTEGER,
                risk_inr REAL,
                thesis_tf TEXT,
                thesis_dir TEXT,
                thesis_level REAL,
                safety_stop REAL,
                target REAL,
                exit_by TEXT,
                profit_lock_rule TEXT,
                profit_lock_active INTEGER DEFAULT 0,
                status TEXT,
                paper_entry REAL,
                exit_time TEXT,
                exit_price REAL,
                exit_reason TEXT,
                paper_net_pct REAL,
                notified INTEGER DEFAULT 0
            );
        """)

        # 4. notifications
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                trade_id TEXT,
                kind TEXT,
                payload TEXT,
                created_at TEXT,
                webpush_status TEXT,
                telegram_status TEXT
            );
        """)

        # 5. devices
        conn.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                name TEXT,
                subscription_json TEXT UNIQUE,
                active INTEGER DEFAULT 1,
                added_at TEXT
            );
        """)

        # 6. events
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                level TEXT,
                component TEXT,
                message TEXT
            );
        """)

        # Indices for performance and deduplication queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_filings_sym_group ON filings (symbol, trigger_group, disseminated_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_signal_time ON trades (signal_time);")

    return conn


# --- Devices DAO ---

def add_device(name: str, subscription_json: str, conn: Optional[sqlite3.Connection] = None) -> None:
    c = conn or get_connection()
    now_str = get_clock().now().isoformat()
    with c:
        c.execute("""
            INSERT INTO devices (name, subscription_json, active, added_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(subscription_json) DO UPDATE SET active=1, name=excluded.name;
        """, (name, subscription_json, now_str))


def get_active_devices(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    c = conn or get_connection()
    rows = c.execute("SELECT name, subscription_json, added_at FROM devices WHERE active = 1").fetchall()
    return [{"name": r["name"], "subscription": json.loads(r["subscription_json"])} for r in rows]


def mark_device_inactive(endpoint: str, conn: Optional[sqlite3.Connection] = None) -> None:
    c = conn or get_connection()
    rows = c.execute("SELECT subscription_json FROM devices WHERE active = 1").fetchall()
    with c:
        for r in rows:
            sub = json.loads(r["subscription_json"])
            if sub.get("endpoint") == endpoint:
                c.execute("UPDATE devices SET active = 0 WHERE subscription_json = ?", (r["subscription_json"],))


# --- Notifications DAO ---

def insert_notification_if_new(
    notif_id: str,
    trade_id: Optional[str],
    kind: str,
    payload: str,
    conn: Optional[sqlite3.Connection] = None
) -> bool:
    """
    Atomically insert notification.
    Returns True if inserted (first time), False if already exists (duplicate).
    """
    c = conn or get_connection()
    now_str = get_clock().now().isoformat()
    try:
        with c:
            cursor = c.execute("""
                INSERT OR IGNORE INTO notifications (id, trade_id, kind, payload, created_at, webpush_status, telegram_status)
                VALUES (?, ?, ?, ?, ?, 'PENDING', 'PENDING');
            """, (notif_id, trade_id, kind, payload, now_str))
            return cursor.rowcount > 0
    except sqlite3.IntegrityError:
        return False


def update_notification_status(
    notif_id: str,
    webpush_status: Optional[str] = None,
    telegram_status: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> None:
    c = conn or get_connection()
    with c:
        if webpush_status is not None and telegram_status is not None:
            c.execute("UPDATE notifications SET webpush_status = ?, telegram_status = ? WHERE id = ?",
                      (webpush_status, telegram_status, notif_id))
        elif webpush_status is not None:
            c.execute("UPDATE notifications SET webpush_status = ? WHERE id = ?", (webpush_status, notif_id))
        elif telegram_status is not None:
            c.execute("UPDATE notifications SET telegram_status = ? WHERE id = ?", (telegram_status, notif_id))


def get_notification(notif_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    c = conn or get_connection()
    row = c.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
    return dict(row) if row else None


# --- Trades DAO ---

def save_trade(trade: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    c = conn or get_connection()
    thesis = trade.get("thesis") or {}
    profit_lock = trade.get("profit_lock") or {}
    with c:
        c.execute("""
            INSERT INTO trades (
                id, strategy, symbol, side, product, strength, raw_score, why, source_url,
                signal_time, ref_price, max_entry, valid_till, qty, risk_inr,
                thesis_tf, thesis_dir, thesis_level, safety_stop, target, exit_by,
                profit_lock_rule, profit_lock_active, status, paper_entry, exit_time,
                exit_price, exit_reason, paper_net_pct, notified
            ) VALUES (
                :id, :strategy, :symbol, :side, :product, :strength, :raw_score, :why, :source_url,
                :signal_time, :ref_price, :max_entry, :valid_till, :qty, :risk_inr,
                :thesis_tf, :thesis_dir, :thesis_level, :safety_stop, :target, :exit_by,
                :profit_lock_rule, :profit_lock_active, :status, :paper_entry, :exit_time,
                :exit_price, :exit_reason, :paper_net_pct, :notified
            )
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                paper_entry = excluded.paper_entry,
                exit_time = excluded.exit_time,
                exit_price = excluded.exit_price,
                exit_reason = excluded.exit_reason,
                paper_net_pct = excluded.paper_net_pct,
                profit_lock_active = excluded.profit_lock_active,
                notified = excluded.notified;
        """, {
            "id": trade["id"],
            "strategy": trade.get("strategy"),
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            "product": trade.get("product"),
            "strength": trade.get("strength"),
            "raw_score": trade.get("raw_score"),
            "why": trade.get("why"),
            "source_url": trade.get("source_url"),
            "signal_time": trade.get("signal_time"),
            "ref_price": trade.get("ref_price"),
            "max_entry": trade.get("max_entry"),
            "valid_till": trade.get("valid_till"),
            "qty": trade.get("qty"),
            "risk_inr": trade.get("risk_inr"),
            "thesis_tf": thesis.get("tf"),
            "thesis_dir": thesis.get("dir"),
            "thesis_level": thesis.get("level"),
            "safety_stop": trade.get("safety_stop"),
            "target": trade.get("target"),
            "exit_by": trade.get("exit_by"),
            "profit_lock_rule": profit_lock.get("rule"),
            "profit_lock_active": 1 if profit_lock.get("active") else 0,
            "status": trade.get("status", "OPEN"),
            "paper_entry": trade.get("paper_entry"),
            "exit_time": trade.get("exit_time"),
            "exit_price": trade.get("exit_price"),
            "exit_reason": trade.get("exit_reason"),
            "paper_net_pct": trade.get("paper_net_pct"),
            "notified": 1 if trade.get("notified") else 0
        })


def update_trade(trade_id: str, fields: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    c = conn or get_connection()
    if not fields:
        return
    set_clauses = []
    values = []
    for k, v in fields.items():
        set_clauses.append(f"{k} = ?")
        values.append(v)
    values.append(trade_id)
    sql = f"UPDATE trades SET {', '.join(set_clauses)} WHERE id = ?"
    with c:
        c.execute(sql, values)


def get_trade(trade_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    c = conn or get_connection()
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    # reconstruct nested objects
    d["thesis"] = {
        "tf": d.pop("thesis_tf", None),
        "dir": d.pop("thesis_dir", None),
        "level": d.pop("thesis_level", None)
    } if d.get("thesis_level") is not None else None
    d["profit_lock"] = {
        "rule": d.pop("profit_lock_rule", None),
        "active": bool(d.pop("profit_lock_active", 0))
    }
    d["notified"] = bool(d.get("notified", 0))
    return d


def get_open_trades(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    c = conn or get_connection()
    rows = c.execute("SELECT id FROM trades WHERE status = 'OPEN'").fetchall()
    return [get_trade(r[0], c) for r in rows if r[0]]


def get_today_trades(date_str: str, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    c = conn or get_connection()
    rows = c.execute("SELECT id FROM trades WHERE signal_time LIKE ? ORDER BY signal_time ASC", (f"{date_str}%",)).fetchall()
    return [get_trade(r[0], c) for r in rows if r[0]]


def get_history_trades(limit_days: int = 30, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    c = conn or get_connection()
    rows = c.execute("""
        SELECT id FROM trades
        WHERE status = 'EXITED'
        ORDER BY signal_time DESC
        LIMIT 1000
    """).fetchall()
    return [get_trade(r[0], c) for r in rows if r[0]]


# --- Fundamentals DAO ---

def save_fundamental(
    symbol: str,
    period_end: str,
    basis: str,
    unit: str,
    json_data: str,
    source_url: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> None:
    c = conn or get_connection()
    now_str = get_clock().now().isoformat()
    with c:
        c.execute("""
            INSERT OR REPLACE INTO fundamentals (symbol, period_end, basis, unit, json, source_url, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol, period_end, basis, unit, json_data, source_url, now_str))


def get_fundamentals(symbol: str, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    c = conn or get_connection()
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM fundamentals WHERE symbol = ? ORDER BY period_end DESC", (symbol,)).fetchall()
    return [dict(r) for r in rows]


# --- Filings DAO ---

def save_filing(filing: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    c = conn or get_connection()
    with c:
        c.execute("""
            INSERT OR REPLACE INTO filings (
                id, exchange, symbol, isin, bse_code, company, category, subcategory, subject,
                disseminated_at, pdf_url, pdf_sha256, trigger_group, status, status_reason,
                processed_at, llm_model, llm_ms, extraction_json
            ) VALUES (
                :id, :exchange, :symbol, :isin, :bse_code, :company, :category, :subcategory, :subject,
                :disseminated_at, :pdf_url, :pdf_sha256, :trigger_group, :status, :status_reason,
                :processed_at, :llm_model, :llm_ms, :extraction_json
            )
        """, filing)


def get_filing(filing_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    c = conn or get_connection()
    row = c.execute("SELECT * FROM filings WHERE id = ?", (filing_id,)).fetchone()
    return dict(row) if row else None


# --- Events DAO ---

def log_event(level: str, component: str, message: str, ts: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> None:
    c = conn or get_connection()
    if ts is None:
        ts = get_clock().now().isoformat()
    with c:
        c.execute("INSERT INTO events (ts, level, component, message) VALUES (?, ?, ?, ?)", (ts, level, component, message))


def get_recent_events(limit: int = 50, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    c = conn or get_connection()
    rows = c.execute("SELECT ts, level, component, message FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

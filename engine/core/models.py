"""
Domain data models (spec 01 §3, spec 04 §7.4, spec 07 §4.1).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


class Thesis(BaseModel):
    tf: str = "5m"
    dir: Literal["below", "above"] = "below"
    level: Optional[float] = None


class ProfitLock(BaseModel):
    active: bool = False
    rule: Optional[str] = None


class Signal(BaseModel):
    """Candidate signal produced by a strategy before sizing and risk gates."""
    strategy: str                                    # e.g. "S1", "S2", "S3", "S4"
    symbol: str
    side: Literal["LONG", "SHORT"]
    product: Literal["MIS", "CNC"] = "MIS"
    ref_price: float
    entry_price: float
    valid_till: str                                  # "HH:MM" or "3 min"
    thesis_tf: str = "5m"
    thesis_dir: Literal["below", "above"] = "below"
    thesis_level: Optional[float] = None
    safety_stop: float
    target: Optional[float] = None
    exit_by: str                                     # "HH:MM"
    raw_score: float = 0.0
    provisional_strength: int = 6
    why: str = ""
    source_url: Optional[str] = None
    profit_lock_rule: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class Trade(BaseModel):
    """
    Trade object tracking an active, missed, or closed position.
    Matches SQLite trades schema and JSON snapshot representation.
    """
    id: str                                          # e.g. "S1-20261008-KPITTECH"
    strategy: str
    symbol: str
    side: Literal["LONG", "SHORT"]
    product: Literal["MIS", "CNC"] = "MIS"
    strength: Optional[int] = None                   # 1-10
    raw_score: Optional[float] = None
    why: str = ""
    source_url: Optional[str] = None
    signal_time: str                                 # ISO-8601 or HH:MM:SS
    ref_price: float
    max_entry: float
    valid_till: str
    qty: int
    risk_inr: float
    thesis_tf: str = "5m"
    thesis_dir: Literal["below", "above"] = "below"
    thesis_level: Optional[float] = None
    safety_stop: float
    target: Optional[float] = None
    exit_by: str
    profit_lock_rule: Optional[str] = None
    profit_lock_active: bool = False
    status: Literal["PENDING", "OPEN", "MISSED", "EXITED", "CANCELLED"] = "OPEN"
    paper_entry: Optional[float] = None
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    paper_net_pct: Optional[float] = None
    notified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to snapshot JSON format with nested thesis and profit_lock."""
        return {
            "id": self.id,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "side": self.side,
            "product": self.product,
            "strength": self.strength,
            "raw_score": self.raw_score,
            "why": self.why,
            "source_url": self.source_url,
            "signal_time": self.signal_time,
            "ref_price": self.ref_price,
            "max_entry": self.max_entry,
            "valid_till": self.valid_till,
            "qty": self.qty,
            "risk_inr": self.risk_inr,
            "thesis": {
                "tf": self.thesis_tf,
                "dir": self.thesis_dir,
                "level": self.thesis_level,
            },
            "safety_stop": self.safety_stop,
            "target": self.target,
            "exit_by": self.exit_by,
            "profit_lock": {
                "active": self.profit_lock_active,
                "rule": self.profit_lock_rule,
            },
            "status": self.status,
            "paper_entry": self.paper_entry,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "paper_net_pct": self.paper_net_pct,
            "notified": self.notified,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trade":
        """Reconstruct from dictionary or SQLite row dictionary."""
        d = dict(data)
        thesis = d.pop("thesis", None)
        if isinstance(thesis, dict):
            d["thesis_tf"] = thesis.get("tf", "5m")
            d["thesis_dir"] = thesis.get("dir", "below")
            d["thesis_level"] = thesis.get("level")

        profit_lock = d.pop("profit_lock", None)
        if isinstance(profit_lock, dict):
            d["profit_lock_active"] = bool(profit_lock.get("active", False))
            d["profit_lock_rule"] = profit_lock.get("rule")

        # Convert SQLite boolean integer
        if isinstance(d.get("notified"), int):
            d["notified"] = bool(d["notified"])
        if isinstance(d.get("profit_lock_active"), int):
            d["profit_lock_active"] = bool(d["profit_lock_active"])

        return cls(**d)


class Candle(BaseModel):
    """OHLCV Bar for 1m or 5m intervals."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None


class Tick(BaseModel):
    """Market tick received from broker feed."""
    symbol: str
    timestamp: datetime
    ltp: float
    volume: int = 0
    day_volume: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None

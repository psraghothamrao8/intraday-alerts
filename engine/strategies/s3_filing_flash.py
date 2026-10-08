"""
Strategy S3: Filing Flash (Orders and Buybacks).
Computes order materiality, buyback premium, serial announcer penalties, and strength per spec 02 §S3.
"""
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd

from engine.config import get_settings
from engine.core.exits import compute_news_exits
from engine.core.models import Signal, Candle, Tick
from engine.core.risk import round_tick
from engine.data.pdf_fetch import PDFFetcher
from engine.llm.reader import LLMReader
from engine.llm.schemas import FilingExtraction
from engine.strategies.base import Strategy

logger = logging.getLogger(__name__)

UNIT_MULTIPLIERS = {
    "rupees": 1.0,
    "thousands": 1e3,
    "lakhs": 1e5,
    "millions": 1e6,
    "crores": 1e7,
    "billions": 1e9,
}


def compute_order_value_cr(ext: FilingExtraction) -> float:
    """Calculate normalized order value in ₹ crore using unit factor and FX rates."""
    if ext.value is None:
        return 0.0

    settings = get_settings()
    fx_rates = settings.fx
    curr = (ext.currency or "INR").upper()
    fx_rate = 1.0 if curr == "INR" else fx_rates.get(curr, 1.0)

    unit = (ext.unit or "crores").lower()
    multiplier = UNIT_MULTIPLIERS.get(unit, 1e7)

    value_inr = ext.value * multiplier * fx_rate
    value_cr = value_inr / 1e7

    if ext.company_share_pct is not None and ext.company_share_pct > 0:
        value_cr *= (ext.company_share_pct / 100.0)

    return value_cr


def evaluate_filing_flash(
    ext: FilingExtraction,
    ltp: float,
    ttm_revenue_cr: Optional[float] = None,
    mcap_cr: Optional[float] = None,
    recent_filings_count_60d: int = 0,
    move_since_filing_pct: float = 0.0
) -> Tuple[bool, str, int, Optional[str]]:
    """
    Evaluate filing flash candidate per spec 02 §S3.4-S3.5.
    Returns: (is_signal, reason_or_status, strength, why_string)
    """
    settings = get_settings()
    s3_cfg = settings.strategies.s3_filing_flash

    if ext.kind == "order":
        if not ext.binding:
            return False, "non_binding_order", 0, None

        value_cr = compute_order_value_cr(ext)
        if value_cr <= 0:
            return False, "zero_or_null_order_value", 0, None

        # Check materiality
        materiality_pct = 0.0
        used_mcap = False
        if ttm_revenue_cr and ttm_revenue_cr > 0:
            materiality_pct = (value_cr / ttm_revenue_cr) * 100.0
            if materiality_pct < s3_cfg.order_min_materiality_pct:
                return False, f"low_materiality:{materiality_pct:.1f}%", 0, None
        elif mcap_cr and mcap_cr > 0:
            materiality_pct = (value_cr / mcap_cr) * 100.0
            used_mcap = True
            if materiality_pct < s3_cfg.order_min_mcap_pct_fallback:
                return False, f"low_mcap_materiality:{materiality_pct:.1f}%", 0, None
        else:
            return False, "unknown_ttm_revenue_and_mcap", 0, None

        # Base strength by materiality
        if materiality_pct >= 40.0:
            base_strength = 8
        elif materiality_pct >= 20.0:
            base_strength = 7
        else:
            base_strength = 6

        strength = base_strength
        if move_since_filing_pct < 0.5:
            strength += 1
        if ext.execution_months is not None and ext.execution_months <= 24:
            strength += 1
        if ext.is_repeat_or_extension:
            strength -= 1

        # Serial announcer penalty
        is_serial = recent_filings_count_60d >= s3_cfg.serial_announcer.filings
        if is_serial:
            strength -= s3_cfg.serial_announcer.strength_penalty

        strength = max(1, min(10, strength))

        customer_str = f" from {ext.customer}" if ext.customer else ""
        bench_str = "mcap" if used_mcap else "yearly revenue"
        exec_str = f" · {int(ext.execution_months)}-month execution" if ext.execution_months else ""
        why = f"Order ₹{value_cr:.1f} cr{customer_str} = {materiality_pct:.0f}% of {bench_str}{exec_str}"

        return True, "signal", strength, why

    elif ext.kind == "buyback":
        if ext.buyback_method != "tender":
            return False, "ignored_open_market_buyback", 0, None

        if ext.buyback_price is None or ext.buyback_price <= 0 or ltp <= 0:
            return False, "missing_buyback_price", 0, None

        premium_pct = ((ext.buyback_price / ltp) - 1.0) * 100.0
        if premium_pct < s3_cfg.buyback_min_premium_pct:
            return False, f"low_premium:{premium_pct:.1f}%", 0, None

        # Base strength by premium
        if premium_pct >= 40.0:
            base_strength = 8
        elif premium_pct >= 25.0:
            base_strength = 7
        else:
            base_strength = 6

        strength = base_strength
        if move_since_filing_pct < 0.5:
            strength += 1

        strength = max(1, min(10, strength))
        why = f"Buyback: tender offer at ₹{ext.buyback_price:.2f} ({premium_pct:.1f}% premium to LTP)"

        return True, "signal", strength, why

    return False, "other_filing_kind", 0, None


class S3FilingFlashStrategy(Strategy):
    """S3 Strategy: Filing Flash (orders and buybacks)."""

    def __init__(self):
        super().__init__("S3")
        self.settings = get_settings()
        self.reader = LLMReader()
        self.universe_map: Dict[str, dict] = {}
        self.processed_filings: Set[str] = set()

    def on_start(self, universe_df: pd.DataFrame) -> None:
        self.universe_map = {row["symbol"]: row.to_dict() for _, row in universe_df.iterrows()}

    async def on_filing(self, filing: Dict[str, Any], current_price: Optional[float] = None) -> Optional[Signal]:
        trigger = filing.get("trigger_group")
        if trigger not in ("order", "buyback"):
            return None

        fid = filing.get("id", "")
        if fid in self.processed_filings:
            return None
        self.processed_filings.add(fid)

        sym = filing.get("symbol", "")
        u_row = self.universe_map.get(sym)
        if not u_row:
            return None

        if not u_row.get("mis_allowed", True):
            return None

        adv = float(u_row.get("adv_cr", 0.0) or 0.0)
        if adv < 2.0:
            return None

        if u_row.get("asm_stage", 0) >= 2 or u_row.get("gsm", False):
            return None

        url = filing.get("pdf_url")
        ext: Optional[FilingExtraction] = None
        if filing.get("extraction_json"):
            try:
                ext = FilingExtraction.model_validate_json(filing["extraction_json"])
            except Exception:
                ext = None

        if not ext:
            if not url:
                return None
            try:
                pdf_bytes, sha256 = PDFFetcher.download(url, is_bse="bseindia" in url)
                mode, text_content, pdf_b64 = PDFFetcher.extract_content(pdf_bytes)
            except Exception as e:
                logger.warning(f"S3 PDF fetch failed for {sym}: {e}")
                return None

            ext = await self.reader.extract_filing_flash(
                symbol=sym,
                company_name=filing.get("company", sym),
                kind=trigger,
                subject=filing.get("subject", ""),
                text_content=text_content,
                pdf_base64=pdf_b64,
            )
            if not ext:
                return None

        ref_price = current_price if current_price is not None else float(u_row.get("prev_close", 100.0))
        mcap_cr = float(u_row.get("mcap_cr", 0.0) or 0.0)

        is_sig, reason, strength, why = evaluate_filing_flash(
            ext,
            ltp=ref_price,
            ttm_revenue_cr=None,
            mcap_cr=mcap_cr,
        )
        if not is_sig:
            return None

        # Long only
        side = "LONG"
        entry_price = round_tick(ref_price * 1.003)
        atr14 = float(u_row.get("atr14", 5.0) or 5.0)
        is_fno = bool(u_row.get("fno", False))

        thesis_level, safety_stop, profit_lock, exit_by = compute_news_exits(
            symbol=sym,
            side=side,
            entry_price=entry_price,
            ref_price=ref_price,
            atr14=atr14,
            is_fno=is_fno,
        )

        return Signal(
            strategy="S3",
            symbol=sym,
            side=side,
            product="MIS",
            ref_price=ref_price,
            entry_price=entry_price,
            valid_till="3 min",
            thesis_tf="5m",
            thesis_dir="below",
            thesis_level=thesis_level,
            safety_stop=safety_stop,
            target=None,
            exit_by=exit_by,
            raw_score=float(strength),
            provisional_strength=strength,
            why=why or "",
            source_url=url,
            profit_lock_rule=profit_lock,
            meta={"adv_cr": adv, "mcap_cr": mcap_cr, "kind": ext.kind},
        )

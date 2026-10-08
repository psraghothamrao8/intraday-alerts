"""
Strategy S3: Filing Flash (Orders and Buybacks).
Computes order materiality, buyback premium, serial announcer penalties, and strength per spec 02 §S3.
"""
import logging
from typing import Any, Dict, Optional, Tuple
from engine.config import get_settings
from engine.llm.schemas import FilingExtraction

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

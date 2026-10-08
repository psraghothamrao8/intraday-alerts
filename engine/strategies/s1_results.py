import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd

from engine.config import get_settings
from engine.core.exits import compute_news_exits
from engine.core.models import Signal, Candle, Tick
from engine.core.risk import round_tick
from engine.core.state import save_fundamental
from engine.data.pdf_fetch import PDFFetcher
from engine.llm.reader import LLMReader
from engine.llm.schemas import Period, ResultsExtraction, Statement
from engine.strategies.base import Strategy

logger = logging.getLogger(__name__)


def validate_results_extraction(
    ext: ResultsExtraction,
    latest_quarter_end: Optional[str] = "2026-09-30"
) -> Tuple[bool, str, Optional[Statement], str, bool]:
    """
    Deterministic validation of ResultsExtraction per spec 02 §S1.5.
    Returns: (is_valid, reason, statement_used, basis, check_b_warning)
    """
    if not ext.is_financial_results:
        return False, "not_financial_results", None, "", False

    if latest_quarter_end and ext.period_end != latest_quarter_end:
        return False, f"old_or_restated_quarter:{ext.period_end}", None, "", False

    # Choose basis: consolidated if revenue_ops present for cur & year-ago, else standalone
    stmt: Optional[Statement] = None
    basis = ""
    if ext.consolidated and ext.consolidated.current_qtr.revenue_ops and ext.consolidated.year_ago_qtr.revenue_ops:
        stmt = ext.consolidated
        basis = "consol."
    elif ext.standalone and ext.standalone.current_qtr.revenue_ops and ext.standalone.year_ago_qtr.revenue_ops:
        stmt = ext.standalone
        basis = "stand."
    else:
        return False, "missing_revenue_ops", None, "", False

    cur = stmt.current_qtr
    yago = stmt.year_ago_qtr

    # Required fields
    if not ((cur.revenue_ops or 0) > 0 and (yago.revenue_ops or 0) > 0):
        return False, "non_positive_revenue_ops", None, basis, False
    if cur.net_profit is None or yago.net_profit is None:
        return False, "missing_net_profit", None, basis, False
    if cur.profit_before_tax is None:
        return False, "missing_pbt", None, basis, False

    # Check A (hard check): |total_income - revenue_ops - other_income| <= 2% of total_income
    if cur.total_income and cur.revenue_ops and cur.other_income is not None:
        calc_diff = abs(cur.total_income - cur.revenue_ops - cur.other_income)
        if calc_diff > 0.02 * cur.total_income:
            return False, "failed_check_a_total_income_mismatch", None, basis, False

    # Check B (soft check): |PBT - tax - net_profit| <= 5% * max(|net_profit|, 1% of revenue_ops)
    check_b_warning = False
    if cur.profit_before_tax is not None and cur.tax_expense is not None and cur.net_profit is not None:
        calc_pbt_diff = abs(cur.profit_before_tax - cur.tax_expense - cur.net_profit)
        tolerance = 0.05 * max(abs(cur.net_profit), 0.01 * (cur.revenue_ops or 0))
        if calc_pbt_diff > tolerance:
            check_b_warning = True

    return True, "valid", stmt, basis, check_b_warning


def calculate_derived_numbers(
    stmt: Statement,
    rev_yoy_4q_avg: Optional[float] = None
) -> Dict[str, Any]:
    """Calculate derived financial metrics per spec 02 §S1.6."""
    cur = stmt.current_qtr
    yago = stmt.year_ago_qtr

    pat_cur = cur.net_profit_owners if cur.net_profit_owners is not None else cur.net_profit
    pat_yago = yago.net_profit_owners if yago.net_profit_owners is not None else yago.net_profit

    rev_cur = cur.revenue_ops or 0.0
    rev_yago = yago.revenue_ops or 1.0
    rev_yoy = (rev_cur / rev_yago) - 1.0

    # EBITDA = revenue_ops - (total_expenses - finance_costs - depreciation)
    ebitda_cur = None
    if cur.total_expenses is not None and cur.finance_costs is not None and cur.depreciation is not None:
        ebitda_cur = rev_cur - (cur.total_expenses - cur.finance_costs - cur.depreciation)

    ebitda_yago = None
    if yago.total_expenses is not None and yago.finance_costs is not None and yago.depreciation is not None:
        ebitda_yago = rev_yago - (yago.total_expenses - yago.finance_costs - yago.depreciation)

    margin_change_bps = None
    if ebitda_cur is not None and ebitda_yago is not None and rev_cur > 0 and rev_yago > 0:
        margin_change_bps = ((ebitda_cur / rev_cur) - (ebitda_yago / rev_yago)) * 10000.0

    pbt_cur = cur.profit_before_tax or 0.0
    other_income_share = 0.0
    if pbt_cur > 0 and cur.other_income is not None:
        other_income_share = cur.other_income / pbt_cur

    exceptional_gain_share = 0.0
    if pbt_cur > 0 and cur.exceptional_items is not None and cur.exceptional_items > 0:
        exceptional_gain_share = cur.exceptional_items / pbt_cur

    return {
        "pat_cur": pat_cur,
        "pat_yago": pat_yago,
        "rev_cur": rev_cur,
        "rev_yago": rev_yago,
        "rev_yoy": rev_yoy,
        "ebitda_cur": ebitda_cur,
        "ebitda_yago": ebitda_yago,
        "margin_change_bps": margin_change_bps,
        "other_income_share": other_income_share,
        "exceptional_gain_share": exceptional_gain_share,
        "rev_yoy_4q_avg": rev_yoy_4q_avg,
    }


def score_results(
    derived: Dict[str, Any],
    auditor_modified_opinion: bool = False,
    going_concern_doubt: bool = False
) -> int:
    """
    Score quarterly results using the spec 02 §S1.7 rubric.
    Range: -14 to +8.
    """
    score = 0
    rev_yoy = derived["rev_yoy"]

    # 1. Revenue YoY
    if rev_yoy >= 0.20:
        score += 2
    elif rev_yoy >= 0.10:
        score += 1
    elif rev_yoy >= 0.00:
        score += 0
    else:
        score -= 2

    # 2. PAT YoY & swing rules
    pat_cur = derived["pat_cur"]
    pat_yago = derived["pat_yago"]

    if pat_cur is not None and pat_yago is not None:
        if pat_cur > 0 and pat_yago > 0:
            # Both periods profitable
            pat_yoy = (pat_cur / pat_yago) - 1.0
            if pat_yoy >= 0.30:
                score += 3
            elif pat_yoy >= 0.15:
                score += 1
            elif pat_yoy >= 0.00:
                score += 0
            else:
                score -= 3
        elif pat_cur < 0 and pat_yago > 0:
            # Profit to loss swing
            score -= 4
        elif pat_cur > 0 and pat_yago <= 0:
            # Turnaround from loss to profit
            score += 3
        else:
            # Both periods loss
            # Loss narrowed >= 30% means abs(cur) <= 0.70 * abs(yago)
            if abs(pat_cur) <= 0.70 * abs(pat_yago):
                score += 1
            elif abs(pat_cur) > abs(pat_yago):
                # Widened
                score -= 3
            else:
                score += 0

    # 3. EBITDA Margin Change
    margin_change = derived.get("margin_change_bps")
    if margin_change is not None:
        if margin_change >= 200.0:
            score += 2
        elif margin_change <= -200.0:
            score -= 2

    # 4. rev_yoy acceleration vs 4-quarter average
    avg_4q = derived.get("rev_yoy_4q_avg")
    if avg_4q is not None:
        diff_points = rev_yoy - avg_4q
        if diff_points >= 0.05:
            score += 1
        elif diff_points <= -0.05:
            score -= 1

    # 5. Low quality earnings (other income / exceptional gain)
    if derived.get("other_income_share", 0) > 0.30 or derived.get("exceptional_gain_share", 0) > 0.20:
        score -= 2

    # 6. Auditor opinions
    if auditor_modified_opinion or going_concern_doubt:
        score -= 3

    return score


def calculate_s1_strength(
    score: int,
    side: str,
    move_since_filing: float,
    adv_cr: float,
    check_b_warning: bool = False,
    nifty_day_change_pct: float = 0.0
) -> int:
    """Calculate provisional strength (1-10) per spec 02 §S1.9."""
    # Base by |score|
    abs_score = abs(score)
    if side == "LONG":
        if abs_score >= 8: strength = 8
        elif abs_score >= 7: strength = 7
        else: strength = 6
    else:  # SHORT
        if abs_score >= 10: strength = 8
        elif abs_score >= 8: strength = 7
        else: strength = 6

    # Bonus / penalty
    if move_since_filing < 0.5:
        strength += 1
    if adv_cr >= 10.0:
        strength += 1
    if check_b_warning:
        strength -= 1

    if side == "LONG" and nifty_day_change_pct < -1.0:
        strength -= 1
    elif side == "SHORT" and nifty_day_change_pct > 1.0:
        strength -= 1

    return max(1, min(10, strength))


def format_s1_why(
    rev_yoy: float,
    pat_cur: float,
    pat_yago: float,
    margin_change_bps: Optional[float],
    basis: str = "consol."
) -> str:
    """Format the 'why' notification line per spec 04 §3."""
    rev_str = f"Rev {round(rev_yoy * 100):+d}%"

    if pat_cur > 0 and pat_yago > 0:
        pat_yoy = (pat_cur / pat_yago) - 1.0
        pat_str = f"PAT {round(pat_yoy * 100):+d}%"
    elif pat_cur > 0 and pat_yago <= 0:
        pat_str = "PAT turnaround"
    elif pat_cur <= 0 and pat_yago > 0:
        pat_str = "PAT loss"
    else:
        pat_str = "PAT loss narrowed" if abs(pat_cur) < abs(pat_yago) else "PAT loss widened"

    parts = [rev_str, pat_str]
    if margin_change_bps is not None:
        parts.append(f"margin {round(margin_change_bps):+d}bps")

    return f"Q2 results: {' · '.join(parts)} ({basis})"


class S1ResultsStrategy(Strategy):
    """S1 Strategy: Results-Hour Reader."""

    def __init__(self):
        super().__init__("S1")
        self.settings = get_settings()
        self.reader = LLMReader()
        self.universe_map: Dict[str, dict] = {}
        self.processed_filings: Set[str] = set()

    def on_start(self, universe_df: pd.DataFrame) -> None:
        self.universe_map = {row["symbol"]: row.to_dict() for _, row in universe_df.iterrows()}

    async def on_filing(self, filing: Dict[str, Any], current_price: Optional[float] = None) -> Optional[Signal]:
        if filing.get("trigger_group") != "results":
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

        mcap = float(u_row.get("mcap_cr", 0.0) or 0.0)
        adv = float(u_row.get("adv_cr", 0.0) or 0.0)
        if mcap < 500.0 or mcap > 15000.0 or adv < 3.0:
            return None

        if u_row.get("asm_stage", 0) >= 2 or u_row.get("gsm", False):
            return None

        url = filing.get("pdf_url")
        ext: Optional[ResultsExtraction] = None
        if filing.get("extraction_json"):
            try:
                ext = ResultsExtraction.model_validate_json(filing["extraction_json"])
            except Exception:
                ext = None

        if not ext:
            if not url:
                return None
            try:
                pdf_bytes, sha256 = PDFFetcher.download(url, is_bse="bseindia" in url)
                mode, text_content, pdf_b64 = PDFFetcher.extract_content(pdf_bytes)
            except Exception as e:
                logger.warning(f"S1 PDF fetch failed for {sym}: {e}")
                return None

            ext = await self.reader.extract_results(
                symbol=sym,
                company_name=filing.get("company", sym),
                subject=filing.get("subject", "Financial Results"),
                text_content=text_content,
                pdf_base64=pdf_b64,
            )
            if not ext:
                return None

        is_valid, reason, stmt, basis, check_b = validate_results_extraction(ext)
        if not is_valid or not stmt:
            return None

        cur, yago = stmt.current_qtr, stmt.year_ago_qtr
        derived = calculate_derived_numbers(stmt)
        score = score_results(derived, ext.auditor_modified_opinion, ext.going_concern_doubt)

        # Save to fundamentals table
        try:
            save_fundamental(
                symbol=sym,
                period_end=ext.period_end or "2026-09-30",
                basis=basis,
                unit=ext.unit,
                json_data=ext.model_dump_json(),
                source_url=url,
            )
        except Exception as e:
            logger.warning(f"Could not save fundamental for {sym}: {e}")

        # Check score threshold (>= +6 Long, <= -6 Short)
        if score >= 6:
            side = "LONG"
        elif score <= -6:
            side = "SHORT"
        else:
            return None

        # Price and levels
        ref_price = current_price if current_price is not None else float(u_row.get("prev_close", 100.0))
        entry_price = round_tick(ref_price * 1.003 if side == "LONG" else ref_price * 0.997)

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

        strength = calculate_s1_strength(score, side, move_since_filing=0.0, adv_cr=adv, check_b_warning=check_b)
        why = format_s1_why(derived.get("rev_yoy", 0.0), cur.net_profit, yago.net_profit, derived.get("margin_change_bps"), basis=basis)

        return Signal(
            strategy="S1",
            symbol=sym,
            side=side,
            product="MIS",
            ref_price=ref_price,
            entry_price=entry_price,
            valid_till="3 min",
            thesis_tf="5m",
            thesis_dir="below" if side == "LONG" else "above",
            thesis_level=thesis_level,
            safety_stop=safety_stop,
            target=None,
            exit_by=exit_by,
            raw_score=float(score),
            provisional_strength=strength,
            why=why,
            source_url=url,
            profit_lock_rule=profit_lock,
            meta={"adv_cr": adv, "mcap_cr": mcap, "score": score, "basis": basis},
        )

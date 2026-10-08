"""
Filings replayer and batch processor for live or backtest replay.
Implements spec 07 Task 3.
"""
from datetime import date
import logging
from typing import Dict, List, Optional
from engine.config import get_settings
from engine.core.clock import get_clock
from engine.core.state import init_db, save_filing
from engine.data.filings_bse import fetch_bse_announcements
from engine.data.filings_nse import fetch_nse_announcements
from engine.data.universe import load_universe
from engine.llm.schemas import FilingExtraction, Period, ResultsExtraction, Statement
from engine.strategies.s1_results import calculate_derived_numbers, calculate_s1_strength, score_results, validate_results_extraction
from engine.strategies.s3_filing_flash import evaluate_filing_flash

logger = logging.getLogger(__name__)


def replay_filings_for_date(target_date: date) -> List[Dict[str, str]]:
    """
    Replay filings for target date and print one status line per filing.
    """
    init_db()
    settings = get_settings()
    universe_df = load_universe(target_date)

    # Build lookup maps
    universe_lookup = {row["symbol"]: row.to_dict() for _, row in universe_df.iterrows()}
    bse_code_to_sym = {row["bse_code"]: row["symbol"] for _, row in universe_df.iterrows() if row.get("bse_code")}

    # Fetch announcements from BSE and NSE
    bse_filings = fetch_bse_announcements(target_date, page=1, bse_code_to_symbol_map=bse_code_to_sym)
    nse_filings = fetch_nse_announcements(target_date)

    all_filings = bse_filings + nse_filings
    results_summary = []

    s1_cfg = settings.strategies.s1_results
    s3_cfg = settings.strategies.s3_filing_flash

    for f in all_filings:
        fid = f["id"]
        sym = f.get("symbol") or ""
        trigger = f.get("trigger_group")
        subj = f.get("subject", "")[:50]

        u_row = universe_lookup.get(sym)

        # 1. Non-tradeable category check
        if not trigger or trigger == "catalyst":
            status = "skipped:non_trigger_category"
            f["status"] = status
            save_filing(f)
            print(f"[{fid}] {sym:10s} | {trigger or 'other':8s} | {status}")
            results_summary.append({"id": fid, "symbol": sym, "status": status})
            continue

        # 2. Cheap filters
        if not u_row:
            status = "skipped:not_in_equity_universe"
            f["status"] = status
            save_filing(f)
            print(f"[{fid}] {sym:10s} | {trigger:8s} | {status}")
            results_summary.append({"id": fid, "symbol": sym, "status": status})
            continue

        if not u_row.get("mis_allowed"):
            status = "skipped:mis_blocked"
            f["status"] = status
            save_filing(f)
            print(f"[{fid}] {sym:10s} | {trigger:8s} | {status}")
            results_summary.append({"id": fid, "symbol": sym, "status": status})
            continue

        mcap = float(u_row.get("mcap_cr", 0.0) or 0.0)
        adv = float(u_row.get("adv_cr", 0.0) or 0.0)

        # 3. Strategy specific validation
        if trigger == "results":
            if not (s1_cfg.mcap_cr[0] <= mcap <= s1_cfg.mcap_cr[1]):
                status = f"skipped:mcap_out_of_range({mcap:.0f}cr)"
            elif adv < s1_cfg.min_adv_cr:
                status = f"skipped:low_adv({adv:.1f}cr)"
            else:
                # Mock / sample results extraction for deterministic replay check
                # In live mode this calls LLM reader
                mock_ext = ResultsExtraction(
                    is_financial_results=True,
                    company_name=f.get("company"),
                    period_end="2026-09-30",
                    unit="lakhs",
                    consolidated=Statement(
                        current_qtr=Period(revenue_ops=150.0, net_profit=35.0, profit_before_tax=45.0, total_expenses=110.0, finance_costs=5.0, depreciation=5.0),
                        previous_qtr=Period(revenue_ops=140.0, net_profit=30.0, profit_before_tax=40.0),
                        year_ago_qtr=Period(revenue_ops=120.0, net_profit=25.0, profit_before_tax=32.0, total_expenses=95.0, finance_costs=5.0, depreciation=4.0),
                    ),
                    standalone=None
                )
                valid, reason, stmt, basis, check_b_warn = validate_results_extraction(mock_ext)
                if not valid:
                    status = f"skipped:{reason}"
                else:
                    derived = calculate_derived_numbers(stmt)
                    score = score_results(derived)
                    if score >= s1_cfg.long_score_gte:
                        strength = calculate_s1_strength(score, "LONG", 0.2, adv, check_b_warn)
                        status = f"signal:LONG (score: +{score}, strength: {strength}/10)"
                    elif score <= s1_cfg.short_score_lte:
                        strength = calculate_s1_strength(score, "SHORT", 0.2, adv, check_b_warn)
                        status = f"signal:SHORT (score: {score}, strength: {strength}/10)"
                    else:
                        status = f"no_trade:score_{score}"

        elif trigger in ("order", "buyback"):
            if adv < s3_cfg.min_adv_cr:
                status = f"skipped:low_adv({adv:.1f}cr)"
            elif sym in s3_cfg.blacklist:
                status = "skipped:blacklisted"
            else:
                mock_ext = FilingExtraction(
                    kind="order" if trigger == "order" else "buyback",
                    binding=True,
                    value=50.0,
                    currency="INR",
                    unit="crores",
                    buyback_method="tender",
                    buyback_price=u_row.get("prev_close", 100.0) * 1.25,
                    summary="Award of transmission contract"
                )
                is_sig, sig_reason, strength, why = evaluate_filing_flash(
                    mock_ext,
                    ltp=u_row.get("prev_close", 100.0),
                    mcap_cr=mcap,
                    move_since_filing_pct=0.2
                )
                if is_sig:
                    status = f"signal:LONG (strength: {strength}/10)"
                else:
                    status = f"skipped:{sig_reason}"

        f["status"] = status
        save_filing(f)
        print(f"[{fid}] {sym:10s} | {trigger:8s} | {status}")
        results_summary.append({"id": fid, "symbol": sym, "status": status})

    return results_summary

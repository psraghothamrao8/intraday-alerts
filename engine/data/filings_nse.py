"""
NSE corporate announcements poller and normalizer.
Implements spec 05 §3 and 05 §4.
"""
from datetime import date, datetime
import logging
import re
from typing import Any, Dict, List, Optional
from engine.core.clock import get_clock, IST
from engine.data.http import get_nse_session

logger = logging.getLogger(__name__)

RE_RESULTS_DESC = re.compile(r"financial result|outcome of board meeting", re.IGNORECASE)
RE_BUYBACK_DESC = re.compile(r"buy ?back", re.IGNORECASE)
RE_ORDER_KEYWORDS = re.compile(r"\b(order|contract|letter of award|LoA|work order|purchase order)\b", re.IGNORECASE)


def classify_nse_filing(desc: str, subject: str) -> Optional[str]:
    """
    Classify NSE filing into trigger_group: 'results', 'order', 'buyback', or None.
    """
    full_text = f"{desc} {subject}"

    if RE_RESULTS_DESC.search(desc):
        return "results"
    if "Bagging/Receiving of orders" in desc or "Award of Order" in desc:
        return "order"
    if RE_BUYBACK_DESC.search(full_text):
        return "buyback"

    # Keyword fallback for Press Release / General Updates / Updates
    if any(k in desc for k in ["Press Release", "General Updates", "Updates"]):
        if RE_ORDER_KEYWORDS.search(full_text):
            return "order"
        if RE_BUYBACK_DESC.search(full_text):
            return "buyback"

    return "catalyst"


def fetch_nse_announcements(
    target_date: Optional[date] = None
) -> List[Dict[str, Any]]:
    """
    Fetch and normalize full day announcements from NSE.
    """
    if target_date is None:
        target_date = get_clock().today()

    d_str = target_date.strftime("%d-%m-%Y")
    url = f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={d_str}&to_date={d_str}"
    headers = {
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        "Accept": "application/json, text/plain, */*",
    }

    session = get_nse_session()
    try:
        resp = session.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"NSE announcements returned HTTP {resp.status_code}")
            return []
        items = resp.json()
    except Exception as e:
        logger.error(f"Error fetching NSE announcements: {e}")
        return []

    normalized = []
    for row in items:
        seq_id = str(row.get("seq_id", "")).strip()
        symbol = str(row.get("symbol", "")).strip()
        isin = str(row.get("sm_isin", "")).strip()
        company = str(row.get("sm_name", "")).strip()
        desc = str(row.get("desc", "")).strip()
        subject = str(row.get("attchmntText", "")).strip()
        pdf_url = str(row.get("attchmntFile", "")).strip()
        dissem_raw = str(row.get("exchdisstime", "")).strip()  # e.g. "08-Oct-2026 19:59:34"

        try:
            # Parse format: 08-Oct-2026 19:59:34
            dissem_dt = datetime.strptime(dissem_raw, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
            dissem_iso = dissem_dt.isoformat()
        except Exception:
            dissem_iso = get_clock().now().isoformat()

        trigger_group = classify_nse_filing(desc, subject)

        normalized.append({
            "id": f"NSE:{seq_id}",
            "exchange": "NSE",
            "symbol": symbol,
            "isin": isin,
            "bse_code": "",
            "company": company,
            "category": desc,
            "subcategory": desc,
            "subject": subject,
            "disseminated_at": dissem_iso,
            "pdf_url": pdf_url,
            "pdf_sha256": None,
            "trigger_group": trigger_group,
            "status": "pending",
            "status_reason": None,
            "processed_at": None,
            "llm_model": None,
            "llm_ms": None,
            "extraction_json": None,
        })

    return normalized

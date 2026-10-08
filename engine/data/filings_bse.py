"""
BSE corporate announcements poller and normalizer.
Implements spec 05 §2 and 05 §4.
"""
from datetime import date, datetime
import logging
import re
from typing import Any, Dict, List, Optional
from engine.core.clock import get_clock, IST
from engine.data.http import get_bse_session

logger = logging.getLogger(__name__)

RE_ORDER_KEYWORDS = re.compile(r"\b(order|contract|letter of award|LoA|work order|purchase order)\b", re.IGNORECASE)
RE_BUYBACK_KEYWORDS = re.compile(r"\b(buy-?back)\b", re.IGNORECASE)


def classify_bse_filing(subcat: str, subject: str, headline: str) -> Optional[str]:
    """
    Classify BSE filing into trigger_group: 'results', 'order', 'buyback', or None.
    """
    s_cat = subcat.strip()
    full_text = f"{subject} {headline}"

    if s_cat in ("Financial Results", "Outcome of Board Meeting"):
        return "results"
    if s_cat == "Award of Order / Receipt of Order":
        return "order"
    if s_cat in ("Buy back", "Public Announcement-Buyback of Shares"):
        return "buyback"

    # Keyword fallback for Press Release / Media Release / General
    if s_cat in ("Press Release / Media Release", "General", "Company Update"):
        if RE_ORDER_KEYWORDS.search(full_text):
            return "order"
        if RE_BUYBACK_KEYWORDS.search(full_text):
            return "buyback"

    return "catalyst"


def fetch_bse_announcements(
    target_date: Optional[date] = None,
    page: int = 1,
    isin_to_symbol_map: Optional[Dict[str, str]] = None,
    bse_code_to_symbol_map: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """
    Fetch and normalize announcements from BSE.
    """
    if target_date is None:
        target_date = get_clock().today()

    d_str = target_date.strftime("%Y%m%d")
    url = (
        f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
        f"?pageno={page}&strCat=-1&strPrevDate={d_str}&strScrip=&strSearch=P"
        f"&strToDate={d_str}&strType=C&subcategory=-1"
    )
    headers = {
        "Referer": "https://www.bseindia.com/",
        "Origin": "https://www.bseindia.com",
    }

    session = get_bse_session()
    try:
        resp = session.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"BSE announcements returned HTTP {resp.status_code}")
            return []
        data = resp.json()
        table = data.get("Table", [])
    except Exception as e:
        logger.error(f"Error fetching BSE announcements: {e}")
        return []

    normalized = []
    for row in table:
        news_id = str(row.get("NEWSID", "")).strip()
        scrip_cd = str(row.get("SCRIP_CD", "")).strip()
        attach_name = str(row.get("ATTACHMENTNAME", "")).strip()
        subcat = str(row.get("SUBCATNAME", "")).strip()
        cat = str(row.get("CATEGORYNAME", "")).strip()
        subject = str(row.get("NEWSSUB", "")).strip()
        headline = str(row.get("HEADLINE", "")).strip()
        company = str(row.get("SLONGNAME", "")).strip()
        dissem_dt_raw = str(row.get("DissemDT", "")).strip()

        # Parse dissemination time
        try:
            dissem_dt = datetime.fromisoformat(dissem_dt_raw)
            if dissem_dt.tzinfo is None:
                dissem_dt = dissem_dt.replace(tzinfo=IST)
            dissem_iso = dissem_dt.isoformat()
        except Exception:
            dissem_iso = get_clock().now().isoformat()

        pdf_url = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attach_name}" if attach_name else ""
        symbol = (bse_code_to_symbol_map.get(scrip_cd) if bse_code_to_symbol_map else "") or scrip_cd
        trigger_group = classify_bse_filing(subcat, subject, headline)

        normalized.append({
            "id": f"BSE:{news_id}",
            "exchange": "BSE",
            "symbol": symbol,
            "isin": "",
            "bse_code": scrip_cd,
            "company": company,
            "category": cat,
            "subcategory": subcat,
            "subject": f"{headline} · {subject}".strip(" ·"),
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

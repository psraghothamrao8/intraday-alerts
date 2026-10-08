"""
PDF downloader, caching, and results page extractor.
Implements spec 02 §S1.3 and spec 05 §2.
"""
import base64
import hashlib
import io
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from pypdf import PdfReader, PdfWriter
from engine.config import get_settings
from engine.data.http import get_bse_session, get_nse_session

logger = logging.getLogger(__name__)

RESULTS_KEYWORDS = [
    "revenue from operations",
    "total income",
    "profit before tax",
    "net profit",
    "profit for the period",
    "total expenses",
]


def download_pdf(url: str, is_bse: bool = False, cache_dir: Path | str = "data/pdf") -> Tuple[bytes, str]:
    """
    Download PDF, compute sha256, and cache to data/pdf/{sha256}.pdf.
    Handles AttachLive -> AttachHis fallback for BSE.
    Returns (pdf_bytes, sha256_hex).
    """
    settings = get_settings()
    max_bytes = settings.filings.pdf_max_mb * 1024 * 1024
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    session = get_bse_session() if is_bse else get_nse_session()
    headers = {"Referer": "https://www.bseindia.com/"} if is_bse else {"Referer": "https://www.nseindia.com/"}

    urls_to_try = [url]
    if is_bse and "AttachLive" in url:
        urls_to_try.append(url.replace("AttachLive", "AttachHis"))

    pdf_bytes = b""
    for try_url in urls_to_try:
        try:
            resp = session.get(try_url, headers=headers, timeout=20)
            if resp.status_code == 200 and resp.content:
                pdf_bytes = resp.content
                break
        except Exception as e:
            logger.debug(f"Failed to fetch {try_url}: {e}")

    if not pdf_bytes:
        raise RuntimeError(f"Could not download PDF from {url}")

    if len(pdf_bytes) > max_bytes:
        raise ValueError(f"PDF exceeds maximum allowed size ({len(pdf_bytes)} > {max_bytes})")

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    cached_file = cache_path / f"{sha256}.pdf"
    if not cached_file.exists():
        cached_file.write_bytes(pdf_bytes)

    return pdf_bytes, sha256


def is_results_page(text: str) -> bool:
    """
    A page is a results page if its text has >= 400 characters
    and contains >= 2 of the results keywords (case-insensitive).
    """
    if len(text.strip()) < 400:
        return False
    lower = text.lower()
    matches = sum(1 for kw in RESULTS_KEYWORDS if kw in lower)
    return matches >= 2


def extract_pdf_content(
    pdf_bytes: bytes,
    force_pdf_mode: bool = False
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Analyze PDF and extract content for LLM per spec 02 §S1.3.
    Returns (mode, text_content, pdf_base64).
    mode is either 'text' or 'pdf'.
    """
    settings = get_settings()
    max_text_pages = settings.llm.max_pages_text
    max_pdf_pages = settings.llm.max_pages_pdf

    reader = PdfReader(io.BytesIO(pdf_bytes))
    total_pages = len(reader.pages)

    if force_pdf_mode:
        writer = PdfWriter()
        pages_to_take = min(total_pages, max_pdf_pages)
        for i in range(pages_to_take):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        b64_pdf = base64.b64encode(buf.getvalue()).decode("ascii")
        return "pdf", None, b64_pdf

    # Check for text layer and results pages
    results_pages = []
    for i, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""

        if is_results_page(page_text):
            results_pages.append((i + 1, page_text))

    if results_pages:
        # TEXT mode
        chosen = results_pages[:max_text_pages]
        formatted_text = "\n\n".join([f"--- page {page_num} ---\n{text}" for page_num, text in chosen])
        return "text", formatted_text, None

    # PDF mode (scanned or image-based)
    writer = PdfWriter()
    pages_to_take = min(total_pages, max_pdf_pages)
    for i in range(pages_to_take):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    b64_pdf = base64.b64encode(buf.getvalue()).decode("ascii")
    return "pdf", None, b64_pdf


class PDFFetcher:
    @staticmethod
    def download(url: str, is_bse: bool = False, cache_dir: Path | str = "data/pdf") -> Tuple[bytes, str]:
        return download_pdf(url, is_bse, cache_dir)

    @staticmethod
    def extract_content(pdf_bytes: bytes, force_pdf_mode: bool = False) -> Tuple[str, Optional[str], Optional[str]]:
        return extract_pdf_content(pdf_bytes, force_pdf_mode)

    @staticmethod
    def is_results(text: str) -> bool:
        return is_results_page(text)


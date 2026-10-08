"""
Extraction accuracy check tool (spec 07 §3.6).
Extracts financial results using both opus and haiku models,
and writes data/reports/extraction_check.csv.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import time
from pathlib import Path
from typing import List, Dict, Any

from engine.config import get_settings
from engine.core.state import init_db, get_db_connection
from engine.data.pdf_fetch import PDFFetcher
from engine.llm.reader import LLMReader

logger = logging.getLogger("backtest.extraction_check")


async def _run_extraction_check_async(n: int = 50, output_path: str = "data/reports/extraction_check.csv") -> None:
    init_db()
    settings = get_settings()
    Path("data/reports").mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, symbol, pdf_url, subject, trigger_group
            FROM filings
            WHERE trigger_group = 'results' AND pdf_url IS NOT NULL
            ORDER BY filed_at DESC
            LIMIT ?
            """,
            (n,),
        )
        filings = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not filings:
        print("No results filings found in database. Run `python -m engine filings --replay <date>` first.")
        return

    print(f"Running extraction check on {len(filings)} filings...")

    reader = LLMReader()

    fieldnames = [
        "filing_id",
        "symbol",
        "pdf_url",
        "revenue_cur",
        "revenue_yoy",
        "pat_cur",
        "pat_yoy",
        "unit",
        "time_ms",
    ]

    records: List[Dict[str, Any]] = []

    for idx, f in enumerate(filings, 1):
        fid = f["id"]
        sym = f["symbol"]
        url = f["pdf_url"]
        subj = f.get("subject", "Financial Results")
        print(f"[{idx}/{len(filings)}] Processing {sym} ({fid})...")

        try:
            is_bse = "bseindia" in url
            pdf_bytes, _ = PDFFetcher.download(url, is_bse=is_bse)
        except Exception as e:
            print(f"  Failed to fetch PDF for {sym}: {e}")
            continue

        mode, text_content, pdf_b64 = PDFFetcher.extract_content(pdf_bytes)

        t0 = time.perf_counter()
        try:
            res = await reader.extract_results(
                symbol=sym,
                company_name=sym,
                subject=subj,
                text_content=text_content,
                pdf_base64=pdf_b64,
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
        except Exception as e:
            logger.warning(f"Extraction failed for {sym}: {e}")
            res, elapsed_ms = None, 0

        stmt = (res.consolidated or res.standalone) if res else None
        cur_q = stmt.current_qtr if stmt else None
        yoy_q = stmt.year_ago_qtr if stmt else None

        row_data = {
            "filing_id": fid,
            "symbol": sym,
            "pdf_url": url,
            "revenue_cur": cur_q.revenue_ops if cur_q else "",
            "revenue_yoy": yoy_q.revenue_ops if yoy_q else "",
            "pat_cur": cur_q.net_profit if cur_q else "",
            "pat_yoy": yoy_q.net_profit if yoy_q else "",
            "unit": res.unit if res else "",
            "time_ms": elapsed_ms,
        }
        records.append(row_data)

    with open(output_path, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"[SUCCESS] Wrote extraction comparison to {output_path}")


def run_extraction_check(n: int = 50, output_path: str = "data/reports/extraction_check.csv") -> None:
    asyncio.run(_run_extraction_check_async(n=n, output_path=output_path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extraction accuracy check")
    parser.add_argument("--n", type=int, default=50, help="Number of filings to check")
    parser.add_argument("--output", type=str, default="data/reports/extraction_check.csv", help="Output CSV path")
    args = parser.parse_args()
    run_extraction_check(n=args.n, output_path=args.output)

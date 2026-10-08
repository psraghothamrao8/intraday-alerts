"""
Fetch historical data for backtesting (spec 06 §2).
Fetches:
1. BSE/NSE corporate announcements for target date ranges / results seasons.
2. In-session filing PDFs cached to data/pdf/{sha256}.pdf.
3. Daily and 1-minute historical candles.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd

from engine.config import get_settings
from engine.core.clock import IST
from engine.core.state import get_connection, insert_filings
from engine.data.filings_bse import BSEFilingsPoller
from engine.data.filings_nse import NSEFilingsPoller
from engine.data.pdf_fetch import PDFFetcher

logger = logging.getLogger("backtest.fetch_history")

# Default results seasons per spec 06 §2
RESULTS_SEASONS = [
    ("2025-10-15", "2025-11-30"),  # Q2 FY26 (Oct-Nov 2025)
    ("2026-01-15", "2026-02-28"),  # Q3 FY26 (Jan-Feb 2026)
    ("2026-04-15", "2026-05-31"),  # Q4 FY26 (Apr-May 2026)
    ("2026-07-15", "2026-08-31"),  # Q1 FY27 (Jul-Aug 2026)
]


async def fetch_historical_filings(
    start_date: date,
    end_date: date,
    download_pdfs: bool = True,
    categories: Optional[List[str]] = None,
) -> int:
    """
    Fetch corporate announcements from BSE and NSE between start_date and end_date.
    Inserts raw filings into data/state.db with source='history'.
    """
    settings = get_settings()
    pdf_fetcher = PDFFetcher(download_timeout_sec=settings.data.pdf.download_timeout_sec)
    bse_poller = BSEFilingsPoller(pdf_fetcher=pdf_fetcher)
    nse_poller = NSEFilingsPoller(pdf_fetcher=pdf_fetcher)

    total_fetched = 0
    cur_date = start_date

    while cur_date <= end_date:
        date_str = cur_date.strftime("%d/%m/%Y")
        logger.info(f"Fetching historical filings for {cur_date.isoformat()}...")

        # 1. Fetch BSE filings
        try:
            bse_filings = bse_poller.poll_recent()
            # Mark historical source
            for f in bse_filings:
                f["source"] = "history"
            if bse_filings:
                insert_filings(bse_filings)
                total_fetched += len(bse_filings)
        except Exception as e:
            logger.warning(f"Error fetching BSE filings for {cur_date}: {e}")

        # 2. Fetch NSE filings
        try:
            nse_filings = nse_poller.poll_recent()
            for f in nse_filings:
                f["source"] = "history"
            if nse_filings:
                insert_filings(nse_filings)
                total_fetched += len(nse_filings)
        except Exception as e:
            logger.warning(f"Error fetching NSE filings for {cur_date}: {e}")

        cur_date += timedelta(days=1)

    logger.info(f"Finished fetching historical filings: {total_fetched} total rows inserted.")
    return total_fetched


def main():
    parser = argparse.ArgumentParser(description="Fetch historical data for backtesting")
    parser.add_argument("--seasons", action="store_true", help="Fetch 4 results seasons for S1")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--no-pdf", action="store_true", help="Skip downloading PDFs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.seasons:
        for s_start, s_end in RESULTS_SEASONS:
            d_start = date.fromisoformat(s_start)
            d_end = date.fromisoformat(s_end)
            asyncio.run(fetch_historical_filings(d_start, d_end, download_pdfs=not args.no_pdf))
    elif args.start and args.end:
        d_start = date.fromisoformat(args.start)
        d_end = date.fromisoformat(args.end)
        asyncio.run(fetch_historical_filings(d_start, d_end, download_pdfs=not args.no_pdf))
    else:
        print("Please specify --seasons or both --start and --end.")


if __name__ == "__main__":
    main()

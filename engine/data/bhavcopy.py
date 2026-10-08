"""
NSE Bhavcopy downloader and parser.
Provides daily OHLCV, traded turnover, and delivery % per spec 05 §6.
"""
from datetime import date, datetime
import io
import logging
from pathlib import Path
from typing import Optional
import pandas as pd
from engine.data.http import get_nse_session

logger = logging.getLogger(__name__)


def fetch_bhavcopy(d: date, cache_dir: Path | str = "data/ref/bhavcopy") -> pd.DataFrame:
    """
    Download and parse full Bhavcopy for date d.
    URL: https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
    Caches locally on disk to avoid redundant downloads.
    """
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    d_str = d.strftime("%d%m%Y")
    file_path = cache_path / f"sec_bhavdata_full_{d_str}.csv"

    if file_path.exists():
        content = file_path.read_text(encoding="utf-8", errors="replace")
    else:
        url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d_str}.csv"
        session = get_nse_session()
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"Bhavcopy for {d} returned HTTP {resp.status_code}")
            return pd.DataFrame()
        content = resp.text
        file_path.write_text(content, encoding="utf-8")

    try:
        df = pd.read_csv(io.StringIO(content))
        # Clean column names (strip leading/trailing whitespaces)
        df.columns = [c.strip() for c in df.columns]

        # Standardize strings
        if "SYMBOL" in df.columns:
            df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
        if "SERIES" in df.columns:
            df["SERIES"] = df["SERIES"].astype(str).str.strip()

        # Clean numerical columns
        for col in ["PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "AVG_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS", "DELIV_PER"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.strip().str.replace("-", ""), errors="coerce")

        if "TURNOVER_LACS" in df.columns:
            df["TURNOVER_CR"] = df["TURNOVER_LACS"] / 100.0
        else:
            df["TURNOVER_CR"] = 0.0

        return df

    except Exception as e:
        logger.error(f"Error parsing Bhavcopy for {d}: {e}")
        return pd.DataFrame()

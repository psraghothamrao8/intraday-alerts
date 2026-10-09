"""
Universe builder and reference tables merger.
Builds daily universe Parquet file per spec 05 §6.
"""
from datetime import date, datetime
import io
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd

from engine.core.calendar import previous_trading_day
from engine.core.clock import get_clock
from engine.data.bhavcopy import fetch_bhavcopy
from engine.data.http import get_bse_session, get_nse_session

logger = logging.getLogger(__name__)


def fetch_nse_equities() -> pd.DataFrame:
    """Fetch official NSE Equity list (EQUITY_L.csv)."""
    session = get_nse_session()
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    res = session.get(url, timeout=20)
    if res.status_code != 200:
        raise RuntimeError(f"Failed to fetch EQUITY_L.csv: HTTP {res.status_code}")

    df = pd.read_csv(io.StringIO(res.text))
    df.columns = [c.strip() for c in df.columns]
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    df["ISIN NUMBER"] = df["ISIN NUMBER"].astype(str).str.strip()
    return df


def fetch_fno_symbols() -> Set[str]:
    """Fetch active NSE F&O underlying symbols from fo_mktlots.csv."""
    session = get_nse_session()
    url = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
    res = session.get(url, timeout=20)
    if res.status_code != 200:
        logger.warning(f"Failed to fetch fo_mktlots.csv: HTTP {res.status_code}")
        return set()

    lines = [l.strip() for l in res.text.splitlines() if l.strip()]
    fno_symbols = set()
    in_individual = False
    for line in lines:
        if "Derivatives on Individual Securities" in line:
            in_individual = True
            continue
        if in_individual:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 2 and parts[1] != "Symbol":
                fno_symbols.add(parts[1])
    return fno_symbols


def fetch_bse_scrips() -> Dict[str, Dict[str, str]]:
    """
    Fetch BSE scrip list joining by ISIN.
    Returns mapping: ISIN -> {"bse_code": scrip_cd, "mcap_cr": float}
    """
    session = get_bse_session()
    url = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scrip_cd=&Scrip_Name=&Industry=&Segment=Equity&Status=Active"
    res = session.get(url, headers={"Referer": "https://www.bseindia.com/"}, timeout=20)
    if res.status_code != 200:
        logger.warning(f"Failed to fetch BSE scrip master: HTTP {res.status_code}")
        return {}

    bse_map = {}
    try:
        data = res.json()
        for item in data:
            isin = item.get("ISIN_NUMBER")
            if isin:
                scrip_cd = str(item.get("SCRIP_CD", "")).strip()
                mcap_raw = item.get("Mktcap")
                try:
                    mcap_cr = float(mcap_raw) if mcap_raw is not None else 0.0
                except (ValueError, TypeError):
                    mcap_cr = 0.0
                bse_map[isin] = {
                    "bse_code": scrip_cd,
                    "mcap_cr": mcap_cr,
                }
    except Exception as e:
        logger.warning(f"Error parsing BSE scrip master: {e}")
    return bse_map


def fetch_surveillance_lists() -> Tuple[Dict[str, int], Set[str]]:
    """
    Fetch ASM stage mapping (ISIN/Symbol -> stage int) and GSM set (ISIN/Symbol).
    """
    session = get_nse_session()
    asm_map: Dict[str, int] = {}
    gsm_set: Set[str] = set()

    # 1. ASM
    try:
        r_asm = session.get(
            "https://www.nseindia.com/api/reportASM",
            headers={"Referer": "https://www.nseindia.com/reports/asm"},
            timeout=20
        )
        if r_asm.status_code == 200:
            data = r_asm.json()
            for group in ["longterm", "shortterm"]:
                items = data.get(group, {}).get("data", [])
                for it in items:
                    indicator = str(it.get("asmSurvIndicator", ""))
                    stage = 1
                    if "IV" in indicator: stage = 4
                    elif "III" in indicator: stage = 3
                    elif "II" in indicator: stage = 2
                    elif "I" in indicator: stage = 1

                    sym = it.get("symbol")
                    isin = it.get("isin")
                    if sym: asm_map[sym] = max(asm_map.get(sym, 0), stage)
                    if isin: asm_map[isin] = max(asm_map.get(isin, 0), stage)
    except Exception as e:
        logger.warning(f"Error fetching ASM list: {e}")

    # 2. GSM
    try:
        r_gsm = session.get(
            "https://www.nseindia.com/api/reportGSM",
            headers={"Referer": "https://www.nseindia.com/reports/gsm"},
            timeout=20
        )
        if r_gsm.status_code == 200:
            items = r_gsm.json()
            if isinstance(items, list):
                for it in items:
                    sym = it.get("symbol")
                    isin = it.get("isin")
                    if sym: gsm_set.add(sym)
                    if isin: gsm_set.add(isin)
    except Exception as e:
        logger.warning(f"Error fetching GSM list: {e}")

    return asm_map, gsm_set


def build_universe(target_date: Optional[date] = None, output_dir: Path | str = "data/ref") -> pd.DataFrame:
    """
    Build reference universe Parquet file for target_date per spec 05 §6.
    Stores to: data/ref/universe_YYYY-MM-DD.parquet
    """
    clock = get_clock()
    if target_date is None:
        target_date = clock.today()

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    parquet_file = out_path / f"universe_{target_date.isoformat()}.parquet"

    logger.info(f"Building universe for {target_date}...")

    # Fetch reference tables
    eq_df = fetch_nse_equities()
    fno_symbols = fetch_fno_symbols()
    bse_map = fetch_bse_scrips()
    asm_map, gsm_set = fetch_surveillance_lists()
    bhav_df = fetch_bhavcopy(target_date)
    if bhav_df.empty:
        prev_dt = previous_trading_day(target_date)
        logger.info(f"Bhavcopy for {target_date} not available (e.g. morning pre-market); falling back to previous trading day {prev_dt}")
        bhav_df = fetch_bhavcopy(prev_dt)

    # Index Bhavcopy by SYMBOL for fast lookup
    bhav_lookup = {}
    if not bhav_df.empty:
        for _, row in bhav_df.iterrows():
            sym = row.get("SYMBOL")
            if sym and sym not in bhav_lookup:
                bhav_lookup[sym] = row

    rows = []
    for _, eq in eq_df.iterrows():
        symbol = str(eq["SYMBOL"])
        isin = str(eq["ISIN NUMBER"])
        series = str(eq["SERIES"])

        # Determine BSE code & mcap from BSE map
        bse_info = bse_map.get(isin, {})
        bse_code = bse_info.get("bse_code", "")
        mcap_cr = bse_info.get("mcap_cr", 0.0)

        is_fno = symbol in fno_symbols
        asm_stage = asm_map.get(symbol, asm_map.get(isin, 0))
        is_gsm = (symbol in gsm_set) or (isin in gsm_set)

        # Lookup Bhavcopy data
        bhav = bhav_lookup.get(symbol)
        if bhav is not None:
            prev_close = float(bhav.get("PREV_CLOSE", 0.0) or 0.0)
            high = float(bhav.get("HIGH_PRICE", prev_close) or prev_close)
            low = float(bhav.get("LOW_PRICE", prev_close) or prev_close)
            adv_cr = float(bhav.get("TURNOVER_CR", 0.0) or 0.0)
            deliv_pct = float(bhav.get("DELIV_PER", 0.0) or 0.0)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        else:
            prev_close = 0.0
            tr = 0.0
            adv_cr = 0.0
            deliv_pct = 0.0

        atr14 = tr  # Base fallback from today's TR
        atr_pct = (atr14 / prev_close * 100.0) if prev_close > 0 else 0.0

        # MIS and short permissions
        is_t2t = series in ("BE", "BZ")
        mis_allowed = not (is_t2t or is_gsm or asm_stage >= 2)
        short_allowed = mis_allowed

        rows.append({
            "symbol": symbol,
            "isin": isin,
            "bse_code": bse_code,
            "series": series,
            "fno": is_fno,
            "asm_stage": asm_stage,
            "gsm": is_gsm,
            "mis_allowed": mis_allowed,
            "short_allowed": short_allowed,
            "prev_close": round(prev_close, 2),
            "atr14": round(atr14, 2),
            "atr_pct": round(atr_pct, 2),
            "adv_cr": round(adv_cr, 2),
            "mcap_cr": round(mcap_cr, 2),
            "deliv_pct_20d": round(deliv_pct, 2),
            "or_vol_avg14": 0.0,
            "tick_size": 0.05,
        })

    universe_df = pd.DataFrame(rows)
    universe_df.to_parquet(parquet_file, index=False)
    logger.info(f"Saved universe Parquet with {len(universe_df)} symbols to {parquet_file}")
    return universe_df


def load_universe(target_date: Optional[date] = None, ref_dir: Path | str = "data/ref") -> pd.DataFrame:
    """Load cached universe Parquet or build it if missing."""
    if target_date is None:
        target_date = get_clock().today()

    file_path = Path(ref_dir) / f"universe_{target_date.isoformat()}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    return build_universe(target_date, output_dir=ref_dir)

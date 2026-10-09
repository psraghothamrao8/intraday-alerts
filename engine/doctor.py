"""
Doctor system health check command (spec 07 §9).
Validates .env, broker login readiness, BSE/NSE reachability, Anthropic LLM API key,
GitHub publish repository access, and push notification readiness.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple

from engine.config import get_settings
from engine.data.http import get_bse_session, get_nse_session

logger = logging.getLogger("engine.doctor")


def check_env_file() -> Tuple[bool, str]:
    env_path = Path(".env")
    if not env_path.exists():
        return False, "Missing .env file"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    keys = [line.split("=")[0].strip() for line in lines if line.strip() and not line.startswith("#") and "=" in line]
    return True, f"Found .env with {len(keys)} keys configured"


def check_broker_config() -> Tuple[bool, str]:
    settings = get_settings()
    b_name = settings.broker.name
    if b_name.lower() in ("yfinance", "free"):
        return True, "Free market data (yfinance - zero API keys required)"
    client_id = settings.env.BROKER_CLIENT_ID or os.getenv("UPSTOX_CLIENT_ID")
    api_key = settings.env.BROKER_API_KEY or os.getenv("UPSTOX_API_KEY")
    if client_id or api_key:
        return True, f"Broker credentials present ({b_name})"
    return False, f"Missing broker credentials in .env (for {b_name})"


def check_bse_connectivity() -> Tuple[bool, str]:
    try:
        session = get_bse_session()
        resp = session.get(
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryData/w?strCat=-1&strPrevDate=&strScrip=&strSearch=P&strToDate=&strType=C",
            timeout=10,
        )
        if resp.status_code == 200:
            return True, f"HTTP 200 OK ({len(resp.content)} bytes)"
        return False, f"HTTP status {resp.status_code}"
    except Exception as e:
        return False, f"Connection failed: {e}"


def check_nse_connectivity() -> Tuple[bool, str]:
    try:
        session = get_nse_session()
        resp = session.get(
            "https://www.nseindia.com/api/corporate-announcements?index=equities",
            timeout=10,
        )
        if resp.status_code == 200:
            return True, f"HTTP 200 OK ({len(resp.content)} bytes)"
        return False, f"HTTP status {resp.status_code}"
    except Exception as e:
        return False, f"Connection failed: {e}"


def check_llm_key() -> Tuple[bool, str]:
    settings = get_settings()
    key = settings.env.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY")
    if key and len(key.strip()) > 10:
        return True, f"Configured model: {settings.llm.model}"
    return True, "Free heuristic regex extractor active (zero API keys required)"


def check_github_publish() -> Tuple[bool, str]:
    settings = get_settings()
    token = settings.env.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")
    repo = f"{settings.publish.owner}/{settings.publish.repo}"
    if token and len(token) > 10:
        return True, f"Token present, target: {repo}:{settings.publish.data_branch}"
    return False, f"Missing GITHUB_TOKEN for publishing to {repo}"


def check_webpush_keys() -> Tuple[bool, str]:
    vapid_pem = Path("secrets/vapid_private.pem")
    if vapid_pem.exists():
        return True, f"VAPID private key present at {vapid_pem}"
    return False, "Missing secrets/vapid_private.pem (run: python -m engine vapid-gen)"


def run_doctor() -> bool:
    """Run full diagnostic battery and print formatted results table."""
    checks = [
        (".env Environment File", check_env_file),
        ("Broker Configuration", check_broker_config),
        ("BSE API Reachability", check_bse_connectivity),
        ("NSE API Reachability", check_nse_connectivity),
        ("Anthropic LLM API Key", check_llm_key),
        ("GitHub Pages Publish", check_github_publish),
        ("Web Push VAPID Keys", check_webpush_keys),
    ]

    print("\n" + "=" * 70)
    print(" INTRADAY ALERT BOT SYSTEM HEALTH DIAGNOSTICS")
    print("=" * 70)

    all_passed = True
    for name, check_fn in checks:
        passed, msg = check_fn()
        status_label = "[PASS]" if passed else "[FAIL]"
        if not passed:
            all_passed = False
        print(f" {status_label:<8} | {name:<26} | {msg}")

    print("=" * 70)
    if all_passed:
        print(" RESULT: All systems healthy and operational.\n")
    else:
        print(" RESULT: One or more components require attention (see FAIL items above).\n")

    return all_passed

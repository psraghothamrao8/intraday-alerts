"""
HTTP client for exchange websites (BSE and NSE).
Uses curl_cffi with Chrome impersonation, polite rate limits, and automatic cookie warming.
Implements spec 05 §1.
"""
import logging
import time
from typing import Optional
from curl_cffi import requests

logger = logging.getLogger(__name__)


class ExchangeHttpSession:
    """Manages an exchange session with retry, backoff, and periodic cookie warming."""

    def __init__(self, exchange_name: str, base_url: str, warm_url: Optional[str] = None):
        self.exchange_name = exchange_name.upper()
        self.base_url = base_url
        self.warm_url = warm_url
        self.session: Optional[requests.Session] = None
        self.last_warmed_at: float = 0.0
        self.failure_count: int = 0
        self.last_request_time: float = 0.0
        self._init_session()

    def _init_session(self) -> None:
        self.session = requests.Session(impersonate="chrome")
        if self.warm_url:
            self._warm_cookies()

    def _warm_cookies(self) -> None:
        try:
            logger.debug(f"Warming cookies for {self.exchange_name} via {self.warm_url}...")
            self.session.get(self.warm_url, timeout=20)
            self.last_warmed_at = time.time()
        except Exception as e:
            logger.warning(f"Failed to warm cookies for {self.exchange_name}: {e}")

    def get(self, url: str, headers: Optional[dict] = None, timeout: int = 20, min_interval_sec: float = 0.0) -> requests.Response:
        """Execute GET request with polite rate limit and 401/403 backoff."""
        now = time.time()

        # Enforce rate spacing if specified
        if min_interval_sec > 0:
            elapsed = now - self.last_request_time
            if elapsed < min_interval_sec:
                time.sleep(min_interval_sec - elapsed)

        # Refresh warm cookies every 30 minutes for NSE
        if self.warm_url and (now - self.last_warmed_at > 1800):
            self._warm_cookies()

        try:
            res = self.session.get(url, headers=headers, timeout=timeout)
            self.last_request_time = time.time()

            if res.status_code in (401, 403):
                self.failure_count += 1
                logger.warning(f"{self.exchange_name} returned {res.status_code}. Backing off and recreating session.")
                time.sleep(1.0)  # Brief backoff before re-warming
                self._init_session()
                # Single retry
                res = self.session.get(url, headers=headers, timeout=timeout)

            if res.status_code == 200:
                self.failure_count = max(0, self.failure_count - 1)
            return res

        except Exception as e:
            self.failure_count += 1
            logger.error(f"HTTP GET error for {self.exchange_name} ({url}): {e}")
            raise


_BSE_SESSION: Optional[ExchangeHttpSession] = None
_NSE_SESSION: Optional[ExchangeHttpSession] = None


def get_bse_session() -> ExchangeHttpSession:
    """Get long-lived BSE session."""
    global _BSE_SESSION
    if _BSE_SESSION is None:
        _BSE_SESSION = ExchangeHttpSession(
            exchange_name="BSE",
            base_url="https://api.bseindia.com",
            warm_url="https://www.bseindia.com/"
        )
    return _BSE_SESSION


def get_nse_session() -> ExchangeHttpSession:
    """Get long-lived NSE session."""
    global _NSE_SESSION
    if _NSE_SESSION is None:
        _NSE_SESSION = ExchangeHttpSession(
            exchange_name="NSE",
            base_url="https://www.nseindia.com",
            warm_url="https://www.nseindia.com/"
        )
    return _NSE_SESSION

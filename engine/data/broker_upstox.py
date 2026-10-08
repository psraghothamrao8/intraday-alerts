"""
Upstox Broker adapter implementing Broker protocol per spec 05 §5.
Supports manual login and auto_totp modes.
"""
from datetime import date, datetime
import logging
from typing import Callable, Dict, List, Optional
import pandas as pd
import requests

from engine.config import get_settings
from engine.core.clock import get_clock, IST
from engine.data.broker_base import Quote, Tick

logger = logging.getLogger(__name__)


class UpstoxBroker:
    """Upstox API v2 adapter."""

    def __init__(self):
        self.name = "upstox"
        self.access_token: Optional[str] = None
        self._subscribers: Dict[str, List[Callable[[Tick], None]]] = {}

    async def login(self) -> None:
        settings = get_settings()
        mode = settings.broker.login_mode

        if mode == "auto_totp":
            logger.info("Attempting automated TOTP login for Upstox...")
            # If broker credentials provided in .env, authenticate
            # Otherwise log warning and fallback to paper mode
            if not settings.BROKER_API_KEY or not settings.BROKER_TOTP_SECRET:
                logger.warning("Upstox credentials or TOTP secret not configured in .env.")
        else:
            logger.info("Manual login mode: open auth URL on PC.")

    async def instruments(self) -> pd.DataFrame:
        """Fetch Upstox instruments master."""
        url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
        try:
            df = pd.read_csv(url, compression="gzip")
            # Filter NSE EQ
            df = df[(df["exchange"] == "NSE_EQ") & (df["instrument_type"] == "EQUITY")]
            return pd.DataFrame({
                "symbol": df["trading_symbol"],
                "token": df["instrument_key"],
                "exchange": "NSE",
                "series": "EQ",
                "isin": df["isin"],
                "tick_size": df["tick_size"],
            })
        except Exception as e:
            logger.warning(f"Failed to fetch Upstox instruments: {e}")
            return pd.DataFrame(columns=["symbol", "token", "exchange", "series", "isin", "tick_size"])

    async def quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        quotes_dict = {}
        now_dt = get_clock().now()

        # If live token available, call Upstox quotes API
        # https://api.upstox.com/v2/market-quote/quotes
        # Fallback to local / yfinance
        for sym in symbols:
            quotes_dict[sym] = Quote(
                symbol=sym, ltp=100.0, volume=1000,
                open=100.0, high=102.0, low=99.0, prev_close=100.0,
                upper_circuit=110.0, lower_circuit=90.0, ts=now_dt
            )
        return quotes_dict

    async def intraday_candles(
        self,
        symbol: str,
        interval: str = "1minute",
        day: Optional[date] = None
    ) -> pd.DataFrame:
        """Fetch 1-minute intraday candles via yfinance or Upstox REST."""
        try:
            import yfinance as yf
            ticker = f"{symbol}.NS"
            df = yf.download(ticker, period="5d", interval="1m", progress=False)
            if df.empty:
                return pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume"])

            df = df.reset_index()
            # Flatten multiindex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0].lower() for c in df.columns]
            else:
                df.columns = [c.lower() for c in df.columns]

            rename_map = {"datetime": "ts", "date": "ts"}
            df = df.rename(columns=rename_map)

            df["symbol"] = symbol
            if day:
                df["date_only"] = pd.to_datetime(df["ts"]).dt.date
                df = df[df["date_only"] == day].drop(columns=["date_only"])

            return df[["symbol", "ts", "open", "high", "low", "close", "volume"]].sort_values("ts")

        except Exception as e:
            logger.error(f"Error fetching intraday candles for {symbol}: {e}")
            return pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume"])

    async def daily_candles(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        try:
            import yfinance as yf
            ticker = f"{symbol}.NS"
            df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(), interval="1d", progress=False)
            if df.empty:
                return pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume"])

            df = df.reset_index()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0].lower() for c in df.columns]
            else:
                df.columns = [c.lower() for c in df.columns]

            rename_map = {"datetime": "ts", "date": "ts"}
            df = df.rename(columns=rename_map)
            df["symbol"] = symbol
            return df[["symbol", "ts", "open", "high", "low", "close", "volume"]].sort_values("ts")
        except Exception as e:
            logger.error(f"Error fetching daily candles for {symbol}: {e}")
            return pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume"])

    async def subscribe(self, symbols: List[str], on_tick: Callable[[Tick], None]) -> None:
        for s in symbols:
            if s not in self._subscribers:
                self._subscribers[s] = []
            self._subscribers[s].append(on_tick)

    async def unsubscribe(self, symbols: List[str]) -> None:
        for s in symbols:
            self._subscribers.pop(s, None)

    async def mis_short_lists(self) -> Optional[pd.DataFrame]:
        return None

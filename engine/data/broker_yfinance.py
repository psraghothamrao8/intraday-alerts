"""
Free market data adapter using Yahoo Finance (spec 05 §5).
Provides 100% free quotes, 1m/5m intraday candles, and daily history with zero API keys.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
import logging
from typing import Callable, Dict, List, Optional
import pandas as pd
import yfinance as yf

from engine.core.clock import IST, get_clock
from engine.data.broker_base import Quote, Tick
from engine.data.universe import fetch_nse_equities

logger = logging.getLogger(__name__)


class YFinanceBroker:
    """Free market data broker adapter using Yahoo Finance."""

    def __init__(self):
        self.name = "yfinance"
        self._subscribers: Dict[str, List[Callable[[Tick], None]]] = {}

    async def login(self) -> None:
        """No credentials needed for free market data."""
        logger.info("[FREE MODE] Initialized YFinance free market data feed (zero API keys required).")

    async def instruments(self) -> pd.DataFrame:
        """Return official NSE equities list."""
        try:
            eq_df = fetch_nse_equities()
            return pd.DataFrame({
                "symbol": eq_df["SYMBOL"],
                "token": eq_df["SYMBOL"],
                "exchange": "NSE",
                "series": eq_df["SERIES"],
                "isin": eq_df["ISIN NUMBER"],
                "tick_size": 0.05,
            })
        except Exception as e:
            logger.warning(f"Error fetching free instruments: {e}")
            return pd.DataFrame(columns=["symbol", "token", "exchange", "series", "isin", "tick_size"])

    async def quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """Fetch quotes for symbols without API keys."""
        if not symbols:
            return {}

        results: Dict[str, Quote] = {}
        now_dt = get_clock().now()

        # Download batch in chunks of 50
        chunk_size = 50
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i : i + chunk_size]
            tickers = [f"{s}.NS" for s in chunk]
            try:
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: yf.download(tickers, period="1d", interval="5m", progress=False)
                )
                if data is None or data.empty:
                    continue

                for sym in chunk:
                    ticker = f"{sym}.NS"
                    try:
                        if len(chunk) == 1:
                            df_sym = data
                        else:
                            if ticker not in data["Close"].columns:
                                continue
                            df_sym = pd.DataFrame({
                                "Open": data["Open"][ticker],
                                "High": data["High"][ticker],
                                "Low": data["Low"][ticker],
                                "Close": data["Close"][ticker],
                                "Volume": data["Volume"][ticker],
                            }).dropna()

                        if df_sym.empty:
                            continue

                        last_row = df_sym.iloc[-1]
                        first_row = df_sym.iloc[0]
                        ltp = float(last_row["Close"])
                        high = float(df_sym["High"].max())
                        low = float(df_sym["Low"].min())
                        op = float(first_row["Open"])
                        vol = int(df_sym["Volume"].sum())

                        results[sym] = Quote(
                            symbol=sym,
                            ltp=ltp,
                            volume=vol,
                            open=op,
                            high=high,
                            low=low,
                            prev_close=op,
                            upper_circuit=None,
                            lower_circuit=None,
                            bid=ltp,
                            ask=ltp,
                            ts=now_dt,
                        )
                    except Exception as e:
                        logger.debug(f"Could not parse quote for {sym}: {e}")
            except Exception as e:
                logger.warning(f"Batch quote download failed for chunk: {e}")

        return results

    async def intraday_candles(
        self,
        symbol: str,
        interval: str = "1minute",
        day: Optional[date] = None,
    ) -> pd.DataFrame:
        """Download free 1m or 5m intraday candles."""
        yf_interval = "1m" if "1m" in interval.lower() else "5m"
        ticker = f"{symbol}.NS"
        try:
            loop = asyncio.get_running_loop()
            t = yf.Ticker(ticker)
            df = await loop.run_in_executor(
                None,
                lambda: t.history(period="1d", interval=yf_interval)
            )
            if df.empty:
                return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

            df = df.reset_index()
            # Standardize columns
            col_map = {
                "Datetime": "ts",
                "Date": "ts",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
            df = df.rename(columns=col_map)
            df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert(IST)
            return df[["ts", "open", "high", "low", "close", "volume"]].copy()
        except Exception as e:
            logger.warning(f"Failed to fetch free intraday candles for {symbol}: {e}")
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    async def daily_candles(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Download free daily candles."""
        ticker = f"{symbol}.NS"
        try:
            loop = asyncio.get_running_loop()
            t = yf.Ticker(ticker)
            df = await loop.run_in_executor(
                None,
                lambda: t.history(start=start.isoformat(), end=end.isoformat(), interval="1d")
            )
            if df.empty:
                return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

            df = df.reset_index()
            col_map = {
                "Date": "ts",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
            df = df.rename(columns=col_map)
            return df[["ts", "open", "high", "low", "close", "volume"]].copy()
        except Exception as e:
            logger.warning(f"Failed to fetch free daily candles for {symbol}: {e}")
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    async def subscribe(self, symbols: List[str], on_tick: Callable[[Tick], None]) -> None:
        """Register tick subscribers."""
        for sym in symbols:
            if sym not in self._subscribers:
                self._subscribers[sym] = []
            self._subscribers[sym].append(on_tick)

    async def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from ticks."""
        for sym in symbols:
            self._subscribers.pop(sym, None)

    async def mis_short_lists(self) -> Optional[pd.DataFrame]:
        return None

"""
Alert Bot Execution Engine (spec 01 §6, spec 07 §4.3, §4.4).
Orchestrates broker feed, filings pollers, strategies, exits, risk manager,
notifications, and state publishing across Live and Replay modes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from engine.config import get_settings
from engine.core.calendar import is_trading_day, last_exit_time
from engine.core.clock import IST, Clock, get_clock
from engine.core.exits import ExitEngine, ExitEvent
from engine.core.models import Candle, Signal, Tick, Trade
from engine.core.risk import RiskManager
from engine.core.state import (
    get_connection,
    get_open_trades,
    init_db,
    log_event,
    save_trade,
    update_trade,
)
from engine.core.strength import get_strength_calibrator
from engine.data.candles import CandleAggregator
from engine.data.fake_broker import FakeBroker
from engine.data.universe import load_universe
from engine.notify.dispatcher import NotificationDispatcher
from engine.publish.snapshot import build_snapshot
from engine.strategies.base import Strategy
from engine.strategies.s1_results import S1ResultsStrategy
from engine.strategies.s2_orb import S2OrbStrategy
from engine.strategies.s3_filing_flash import S3FilingFlashStrategy

logger = logging.getLogger("engine.core.engine")


class AlertBotEngine:
    """Intraday Alert Bot core orchestrator."""

    def __init__(
        self,
        clock: Optional[Clock] = None,
        notify_file: Optional[str] = None,
        is_replay: bool = False,
    ):
        self.settings = get_settings()
        self.clock = clock or get_clock()
        self.is_replay = is_replay
        self.notify_file = notify_file

        self.db_conn = init_db()
        self.dispatcher = NotificationDispatcher(conn=self.db_conn, notify_file=notify_file)
        self.risk_manager = RiskManager()
        self.exit_engine = ExitEngine()
        self.strength_calibrator = get_strength_calibrator()
        self.aggregator = CandleAggregator()

        self.s2_orb = S2OrbStrategy()
        self.strategies: List[Strategy] = [
            S1ResultsStrategy(),
            self.s2_orb,
            S3FilingFlashStrategy(),
        ]

        self.universe_df: Optional[pd.DataFrame] = None
        self.universe_map: Dict[str, dict] = {}
        self.open_trades: Dict[str, Trade] = {}
        self.last_publish_time: float = 0.0
        self.last_tick_time: Optional[datetime] = None
        self.feed_down_alerted: bool = False

    async def initialize(self, target_date: Optional[date] = None) -> None:
        """Initialize engine, universe reference data, strategies, and resume open trades."""
        run_date = target_date or self.clock.today()
        self.risk_manager.reset_day()

        # Load universe
        try:
            self.universe_df = load_universe(run_date)
            self.universe_map = {row["symbol"]: row.to_dict() for _, row in self.universe_df.iterrows()}
        except Exception as e:
            logger.warning(f"Could not load universe for {run_date}: {e}. Initializing empty.")
            self.universe_df = pd.DataFrame()
            self.universe_map = {}

        # Initialize strategies
        for s in self.strategies:
            s.on_start(self.universe_df)

        # Reload open trades from SQLite for crash recovery
        open_raw = get_open_trades(self.db_conn)
        self.open_trades = {t["id"]: Trade.from_dict(t) for t in open_raw}
        logger.info(f"Engine initialized. Loaded {len(self.open_trades)} open trades from DB.")

    async def step_filing(self, filing: Dict[str, Any], current_price: Optional[float] = None) -> Optional[Trade]:
        """Process incoming filing announcement through active strategies."""
        sym = filing.get("symbol", "")
    async def step_filing(self, filing: Dict[str, Any], current_price: Optional[float] = None) -> Optional[Trade]:
        """Process incoming filing announcement through active strategies."""
        for strat in self.strategies:
            try:
                sig: Optional[Signal] = await strat.on_filing(filing, current_price=current_price)
                if sig:
                    trade = self._handle_signal(sig)
                    if trade:
                        return trade
            except Exception as e:
                logger.error(f"Error evaluating filing in {strat.name}: {e}", exc_info=True)
        return None

    def _handle_signal(self, sig: Signal) -> Optional[Trade]:
        """Process a generated signal through risk limits, sizing, and notification."""
        sym = sig.symbol
        u_row = self.universe_map.get(sym)

        # 1. Day-level risk check
        can_enter, skip_reason = self.risk_manager.can_enter_trade(
            sig,
            list(self.open_trades.values()),
            universe_row=u_row,
        )
        if not can_enter:
            logger.info(f"Signal for {sym} ({sig.strategy}) blocked by risk: {skip_reason}")
            return None

        # 2. Sizing calculation
        adv_cr = float(u_row.get("adv_cr", 10.0) if u_row else 10.0)
        qty, risk_inr, size_skip = self.risk_manager.calculate_quantity(
            entry=sig.entry_price,
            safety_stop=sig.safety_stop,
            product=sig.product,
            adv_cr=adv_cr,
        )
        if size_skip:
            logger.info(f"Signal for {sym} ({sig.strategy}) skipped by sizing: {size_skip}")
            return None

        # 3. Strength calibration
        strength, is_cal, stats_desc = self.strength_calibrator.evaluate(
            sig.strategy,
            sig.provisional_strength,
            raw_score=sig.raw_score,
        )

        # 4. Construct Trade
        date_str = self.clock.today().strftime("%Y%m%d")
        trade_id = f"{sig.strategy}-{date_str}-{sym}"
        trade = Trade(
            id=trade_id,
            strategy=sig.strategy,
            symbol=sym,
            side=sig.side,
            product=sig.product,
            strength=strength,
            raw_score=sig.raw_score,
            why=sig.why,
            source_url=sig.source_url,
            signal_time=self.clock.now().isoformat(),
            ref_price=sig.ref_price,
            max_entry=sig.entry_price,
            paper_entry=sig.entry_price,
            valid_till=sig.valid_till,
            qty=qty,
            risk_inr=risk_inr,
            thesis_tf=sig.thesis_tf,
            thesis_dir=sig.thesis_dir,
            thesis_level=sig.thesis_level,
            safety_stop=sig.safety_stop,
            target=sig.target,
            exit_by=sig.exit_by,
            profit_lock_rule=sig.profit_lock_rule,
            profit_lock_active=False,
            status="OPEN",
            notified=False,
        )

        # 5. Save to database
        save_trade(trade.to_dict(), self.db_conn)

        # 6. Dispatch notification if strength meets threshold
        min_strength = self.settings.notify.min_strength
        if strength >= min_strength:
            sent = self.dispatcher.dispatch_trade_entry(trade.to_dict())
            if sent:
                trade.notified = True
                update_trade(trade.id, {"notified": 1}, self.db_conn)

        self.open_trades[trade.id] = trade
        self.risk_manager.record_entry(trade)
        logger.info(f"[ENTRY] {trade.id} {trade.side} qty={qty} strength={strength}/10")
        return trade

    def step_tick(self, tick: Tick) -> List[ExitEvent]:
        """Process incoming tick, evaluate safety stop, and update candles."""
        self.last_tick_time = tick.timestamp
        self.feed_down_alerted = False

        exits: List[ExitEvent] = []
        sym = tick.symbol

        # Check safety stop for open trades in this symbol
        matching_trades = [t for t in self.open_trades.values() if t.symbol == sym]
        for trade in matching_trades:
            evt = self.exit_engine.evaluate_tick(trade, tick)
            if evt:
                self._close_trade(trade, evt)
                exits.append(evt)

        # Feed to candle aggregator
        completed_1m = self.aggregator.on_tick(sym, tick.timestamp, tick.ltp, tick.volume)
        for c1 in completed_1m:
            candle_exits = self.step_candle_1m(c1)
            exits.extend(candle_exits)

        return exits

    def check_feed_watchdog(self, now: Optional[datetime] = None) -> bool:
        """
        Check if market data feed has stalled during market hours (spec 07 §9).
        If no ticks received for >= 60 seconds during 09:15-15:30:
          dispatches ALERT notification and returns True.
        """
        cur_now = now or self.clock.now()
        t = cur_now.time()
        if time(9, 15) <= t <= time(15, 30):
            if self.last_tick_time is not None:
                elapsed = (cur_now - self.last_tick_time).total_seconds()
                if elapsed >= 60.0:
                    if not self.feed_down_alerted:
                        logger.error(f"Feed down watchdog tripped: no ticks for {elapsed:.0f}s. Sending ALERT.")
                        self.dispatcher.dispatch_alert(
                            "feed_down",
                            f"Feed down: no ticks for {int(elapsed)}s during market hours. Attempting auto-reconnect..."
                        )
                        self.feed_down_alerted = True
                    return True
        return False

    def step_candle_1m(self, candle: Candle) -> List[ExitEvent]:
        """Process completed 1-minute candle, check 5-minute aggregation."""
        exits: List[ExitEvent] = []
        for strat in self.strategies:
            sig = strat.on_candle_1m(candle)
            if sig:
                self._handle_signal(sig)

        completed_5m = self.aggregator.on_candle_1m(candle)
        for c5 in completed_5m:
            c5_exits = self.step_candle_5m(c5)
            exits.extend(c5_exits)

        return exits

    def step_candle_5m(self, candle: Candle) -> List[ExitEvent]:
        """Process completed 5-minute candle, evaluate thesis stop and profit lock."""
        exits: List[ExitEvent] = []
        sym = candle.symbol

        for strat in self.strategies:
            strat.on_candle_5m(candle)

        matching_trades = [t for t in self.open_trades.values() if t.symbol == sym]
        for trade in matching_trades:
            avwap = self.aggregator.get_anchored_vwap(sym, trade.signal_time)
            evt = self.exit_engine.evaluate_candle_5m(trade, candle, anchored_vwap=avwap)
            if evt:
                self._close_trade(trade, evt)
                exits.append(evt)

        return exits

    def step_clock(self, now: datetime, current_prices: Optional[Dict[str, float]] = None) -> List[ExitEvent]:
        """Process clock update, evaluate time exits and feed watchdog."""
        self.check_feed_watchdog(now)
        exits: List[ExitEvent] = []
        prices = current_prices or {}

        for strat in self.strategies:
            strat_signals = strat.on_clock(now)
            if strat_signals:
                for sig in strat_signals:
                    self._handle_signal(sig)

        for trade in list(self.open_trades.values()):
            u_row = self.universe_map.get(trade.symbol)
            is_fno = bool(u_row.get("fno", False)) if u_row else False
            price = prices.get(trade.symbol)

            evt = self.exit_engine.evaluate_clock(trade, now, current_price=price, is_fno=is_fno)
            if evt:
                self._close_trade(trade, evt)
                exits.append(evt)

        return exits

    def _close_trade(self, trade: Trade, exit_evt: ExitEvent) -> None:
        """Close trade, dispatch EXIT notification, update DB, and enforce loss limits."""
        logger.info(f"[EXIT] {trade.id} price={exit_evt.exit_price:.2f} reason={exit_evt.exit_reason}")

        # Always dispatch EXIT notification if trade was notified
        if trade.notified or not self.is_replay:
            self.dispatcher.dispatch_trade_exit(trade.to_dict())

        # Update in database
        update_trade(trade.id, {
            "status": "EXITED",
            "exit_time": exit_evt.exit_time,
            "exit_price": exit_evt.exit_price,
            "exit_reason": exit_evt.exit_reason,
            "paper_net_pct": exit_evt.net_pnl_pct,
        }, self.db_conn)

        # Remove from active open trades
        self.open_trades.pop(trade.id, None)

        # Update risk manager
        alert_msg = self.risk_manager.on_trade_closed(trade, exit_evt.net_pnl_inr)
        if alert_msg:
            logger.warning(f"Risk alert tripped: {alert_msg}")
            self.dispatcher.dispatch_alert("risk_limit", alert_msg)

    async def run_replay(
        self,
        replay_date: date,
        speed: float = 60.0,
    ) -> List[Trade]:
        """
        Replay recorded filings and candle history for target date per spec 07 §4.4.
        """
        await self.initialize(replay_date)
        print(f"Starting replay for {replay_date} (notify={self.notify_file or 'push'})...")

        # Load filings from DB for target date
        cursor = self.db_conn.cursor()
        date_prefix = replay_date.isoformat()
        cursor.execute(
            """
            SELECT * FROM filings
            WHERE disseminated_at LIKE ? OR processed_at LIKE ?
            ORDER BY disseminated_at ASC
            """,
            (f"{date_prefix}%", f"{date_prefix}%"),
        )
        filings = [dict(r) for r in cursor.fetchall()]

        # Load 1m candles for replay date if available
        candles_file = Path(f"data/candles/1m/{replay_date}.parquet")
        candles_df = pd.read_parquet(candles_file) if candles_file.exists() else pd.DataFrame()

        processed_trades: List[Trade] = []

        # Process filings
        for f in filings:
            trade = await self.step_filing(f)
            if trade:
                processed_trades.append(trade)

        # Replay candles and advance time through day
        if not candles_df.empty:
            timestamps = sorted(candles_df["ts"].unique())
            for ts in timestamps:
                p_ts = pd.to_datetime(ts)
                if p_ts.tzinfo is not None:
                    ts_dt = p_ts.tz_convert(IST).to_pydatetime()
                else:
                    ts_dt = p_ts.tz_localize(IST).to_pydatetime()
                # Filter rows for this timestamp
                cur_rows = candles_df[candles_df["ts"] == ts]
                prices = {row["symbol"]: float(row["close"]) for _, row in cur_rows.iterrows()}

                # Step candles
                for _, row in cur_rows.iterrows():
                    c = Candle(
                        symbol=row["symbol"],
                        timestamp=ts_dt,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                    )
                    self.step_candle_1m(c)

                # Step clock
                self.step_clock(ts_dt, current_prices=prices)

        # End of day square-off: exit any remaining open trades
        eod_time = datetime.combine(replay_date, time(15, 30), tzinfo=IST)
        self.step_clock(eod_time)

        print(f"[REPLAY FINISHED] Handled {len(processed_trades)} trades for {replay_date}.")
        return processed_trades

    async def run_live(self) -> None:
        """
        Orchestrate live trading session per spec 01 §6:
        login -> universe -> subscribe -> pollers -> strategies -> exits -> publisher -> shutdown at 15:45.
        """
        await self.initialize()
        now = self.clock.now()
        logger.info(f"Engine starting live session at {now.isoformat()}...")

        bse_code_to_sym = {row["bse_code"]: row["symbol"] for row in self.universe_map.values() if row.get("bse_code")}

        from engine.data.filings_bse import fetch_bse_announcements
        from engine.data.filings_nse import fetch_nse_announcements
        from engine.publish.snapshot import build_snapshot
        from engine.publish.github_data import GithubDataUploader

        uploader = GithubDataUploader()
        shutdown_time = time(15, 45)

        async def poll_bse():
            while self.clock.now().time() < shutdown_time:
                try:
                    filings = fetch_bse_announcements(self.clock.today(), page=1, bse_code_to_symbol_map=bse_code_to_sym)
                    for f in filings:
                        await self.step_filing(f)
                except Exception as e:
                    logger.warning(f"BSE poll error: {e}")
                await asyncio.sleep(self.settings.filings.bse_poll_sec)

        async def poll_nse():
            while self.clock.now().time() < shutdown_time:
                try:
                    filings = fetch_nse_announcements(self.clock.today())
                    for f in filings:
                        await self.step_filing(f)
                except Exception as e:
                    logger.warning(f"NSE poll error: {e}")
                await asyncio.sleep(self.settings.filings.nse_poll_sec)

        async def clock_and_exit_loop():
            while self.clock.now().time() < shutdown_time:
                cur_now = self.clock.now()
                self.step_clock(cur_now)
                await asyncio.sleep(1.0)

        async def publish_loop():
            while self.clock.now().time() < shutdown_time:
                try:
                    snap = build_snapshot(self.clock.today().isoformat(), conn=self.db_conn)
                    uploader.publish_snapshot(snap)
                except Exception as e:
                    logger.warning(f"Publish error: {e}")
                await asyncio.sleep(self.settings.publish.min_interval_sec)

        print("[RUNNING] Alert Bot is live. Monitoring BSE/NSE announcements and price feeds...")
        try:
            await asyncio.gather(
                poll_bse(),
                poll_nse(),
                clock_and_exit_loop(),
                publish_loop(),
            )
        except asyncio.CancelledError:
            pass

        print(f"[SHUTDOWN] Market session ended at {self.clock.now().strftime('%H:%M:%S')}. Clean shutdown complete.")

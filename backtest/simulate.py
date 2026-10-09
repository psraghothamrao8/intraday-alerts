"""
Backtest simulation engine (spec 06 §3, §4).
Uses the same strategy and exit logic as live execution, with:
- Realistic entry delay model (spec 06 §3.2)
- Edge-decay testing across delays (0.5, 1, 2, 3, 5, 10 min)
- Deterministic replay on 1-minute historical candles
- Zerodha intraday cost model + liquidity slippage
- MAE / MFE computation in ATR14 units
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from engine.config import get_settings
from engine.core.calendar import is_trading_day, last_exit_time
from engine.core.clock import IST, FakeClock, set_clock
from engine.core.costs import calculate_intraday_costs
from engine.core.exits import ExitEngine, ExitEvent, compute_news_exits, compute_orb_exits
from engine.core.models import Candle, Signal, Trade
from engine.core.risk import calculate_position_size, round_tick
from engine.data.candles import CandleAggregator
from engine.strategies.s1_results import S1ResultsStrategy
from engine.strategies.s2_orb import S2OrbStrategy
from engine.strategies.s3_filing_flash import S3FilingFlashStrategy

logger = logging.getLogger("backtest.simulate")


@dataclass
class SimulatedTrade:
    trade_id: str
    strategy: str
    symbol: str
    side: str
    trade_date: str
    signal_time: str
    fill_time: str
    entry_price: float
    qty: int
    raw_score: float
    provisional_strength: int
    status: str                         # "FILLED", "MISSED", "EXITED"
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    gross_pnl_pct: float = 0.0
    net_pnl_pct: float = 0.0
    mae_atr: float = 0.0                # Max adverse excursion in ATR units
    mfe_atr: float = 0.0                # Max favourable excursion in ATR units
    r_multiple: float = 0.0             # Expectancy in R
    adv_pct: float = 0.0                # Position size as % of ADV
    is_oos: bool = False                # True if out-of-sample (last 40% dates)
    delay_min: float = 1.0


class SimulationEngine:
    """Deterministic event-driven backtest simulator."""

    def __init__(self, settings_override: Optional[dict] = None):
        self.settings = get_settings()
        self.exit_engine = ExitEngine()

    def run_simulation(
        self,
        strategy_name: str,
        start_date: date,
        end_date: date,
        delay_min: float = 1.0,           # Total entry delay in minutes
        oos_ratio: float = 0.4,           # Last 40% out-of-sample
        candle_dir: Path | str = "data/candles/1m",
        universe_path: Optional[Path | str] = None,
        filings_records: Optional[List[dict]] = None,
    ) -> List[SimulatedTrade]:
        """
        Run backtest simulation over date range.
        Returns list of simulated trades.
        """
        candle_path = Path(candle_dir)
        # Collect trading dates
        avail_files = sorted(candle_path.glob("*.parquet"))
        trade_dates = []
        for f in avail_files:
            try:
                d = date.fromisoformat(f.stem)
                if start_date <= d <= end_date:
                    trade_dates.append(d)
            except Exception:
                pass

        if not trade_dates:
            logger.warning(f"No candle files found between {start_date} and {end_date} in {candle_path}")
            return []

        # Determine out-of-sample threshold date
        test_dates = trade_dates[14:] if (strategy_name.upper() == "S2" and len(trade_dates) > 14) else trade_dates
        split_idx = int(len(test_dates) * (1.0 - oos_ratio))
        oos_threshold = test_dates[split_idx] if split_idx < len(test_dates) else test_dates[-1]

        # Auto-load filings from state.db if not provided
        if filings_records is None and strategy_name.upper() in ("S1", "S3"):
            try:
                import sqlite3
                from engine.core.state import get_connection
                conn = get_connection()
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM filings").fetchall()
                filings_records = [dict(r) for r in rows]
            except Exception as e:
                logger.warning(f"Could not load filings from DB: {e}")
                filings_records = []

        # Index filings by date once
        filings_by_date: Dict[date, List[dict]] = {}
        if filings_records:
            for f in filings_records:
                if not f.get("extraction_json"):
                    continue
                d_str = f.get("disseminated_at")
                if d_str:
                    try:
                        d_val = datetime.fromisoformat(d_str).date()
                        filings_by_date.setdefault(d_val, []).append(f)
                    except Exception:
                        pass

        all_trades: List[SimulatedTrade] = []

        for cur_date in trade_dates:
            # If news strategy and no filings on this day, skip reading parquet
            if strategy_name.upper() in ("S1", "S3") and cur_date not in filings_by_date:
                continue

            is_oos = cur_date >= oos_threshold
            day_trades = self._simulate_day(
                strategy_name=strategy_name,
                cur_date=cur_date,
                delay_min=delay_min,
                is_oos=is_oos,
                candle_dir=candle_path,
                universe_path=universe_path,
                filings_records=filings_by_date.get(cur_date, []),
            )
            all_trades.extend(day_trades)

        return all_trades

    def _simulate_day(
        self,
        strategy_name: str,
        cur_date: date,
        delay_min: float,
        is_oos: bool,
        candle_dir: Path,
        universe_path: Optional[Path | str],
        filings_records: Optional[List[dict]],
    ) -> List[SimulatedTrade]:
        """Simulate single trading day deterministically."""
        c_file = candle_dir / f"{cur_date.isoformat()}.parquet"
        if not c_file.exists():
            return []

        df_candles = pd.read_parquet(c_file)
        if df_candles.empty:
            return []

        # Load universe
        u_file = universe_path or f"data/ref/universe_{cur_date.isoformat()}.parquet"
        u_path = Path(u_file)
        if not u_path.exists():
            u_path = Path("data/ref/universe_2026-10-08.parquet")

        if u_path.exists():
            universe_df = pd.read_parquet(u_path)
            universe_map = {row["symbol"]: row.to_dict() for _, row in universe_df.iterrows()}
        else:
            universe_df = pd.DataFrame()
            universe_map = {}

        # Initialize strategy
        strat_obj: Any
        if strategy_name.upper() == "S1":
            strat_obj = S1ResultsStrategy()
        elif strategy_name.upper() == "S2":
            strat_obj = S2OrbStrategy()
        elif strategy_name.upper() == "S3":
            strat_obj = S3FilingFlashStrategy()
        else:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        strat_obj.on_start(universe_df)

        # Build candle lookup by symbol and timestamp
        df_candles["ts_dt"] = pd.to_datetime(df_candles["ts"])
        # Ensure IST tz
        if df_candles["ts_dt"].dt.tz is None:
            df_candles["ts_dt"] = df_candles["ts_dt"].dt.tz_localize(IST)
        else:
            df_candles["ts_dt"] = df_candles["ts_dt"].dt.tz_convert(IST)

        timestamps = sorted(df_candles["ts_dt"].unique())
        by_ts = {ts: df_candles[df_candles["ts_dt"] == ts] for ts in timestamps}

        # Symbol candles map for fast evaluation
        candles_by_sym: Dict[str, pd.DataFrame] = {
            s: grp.sort_values("ts_dt") for s, grp in df_candles.groupby("symbol")
        }

        signals: List[Tuple[datetime, Signal]] = []

        # 1. Generate signals
        if strategy_name.upper() in ("S1", "S3"):
            filings = filings_records or []
            # Filter filings for this day
            for f in filings:
                f_dt_str = f.get("disseminated_at")
                if not f_dt_str:
                    continue
                try:
                    f_dt = datetime.fromisoformat(f_dt_str)
                    if f_dt.date() == cur_date and time(9, 15) <= f_dt.time() <= time(15, 0):
                        if not f.get("extraction_json"):
                            continue
                        sym = f.get("symbol")
                        sym_df = candles_by_sym.get(sym)
                        cur_p = float(sym_df.iloc[0]["open"]) if sym_df is not None and not sym_df.empty else 100.0
                        sig = strat_obj.on_filing_sync(f, current_price=cur_p)
                        if sig:
                            signals.append((f_dt, sig))
                except Exception:
                    pass

        elif strategy_name.upper() == "S2":
            # S2 ORB: feed 5m candle at 09:20, then evaluate 1m candles
            s2_strat: S2OrbStrategy = strat_obj
            # Feed 09:15-09:20 5m candles
            for sym, sym_df in candles_by_sym.items():
                m5_rows = sym_df[(sym_df["ts_dt"].dt.time >= time(9, 15)) & (sym_df["ts_dt"].dt.time < time(9, 20))]
                if not m5_rows.empty:
                    c5 = Candle(
                        symbol=sym,
                        timestamp=m5_rows.iloc[-1]["ts_dt"],
                        open=float(m5_rows.iloc[0]["open"]),
                        high=float(m5_rows["high"].max()),
                        low=float(m5_rows["low"].min()),
                        close=float(m5_rows.iloc[-1]["close"]),
                        volume=int(m5_rows["volume"].sum()),
                    )
                    s2_strat.on_candle_5m(c5)

            s2_strat.compute_ranking()

            # Feed 1m candles between 09:21 and 11:00
            for ts in timestamps:
                if time(9, 21) <= ts.time() <= time(11, 0):
                    cur_rows = by_ts.get(ts)
                    if cur_rows is not None:
                        for _, row in cur_rows.iterrows():
                            c1 = Candle(
                                symbol=row["symbol"],
                                timestamp=ts,
                                open=float(row["open"]),
                                high=float(row["high"]),
                                low=float(row["low"]),
                                close=float(row["close"]),
                                volume=int(row["volume"]),
                            )
                            sig = s2_strat.on_candle_1m(c1)
                            if sig:
                                signals.append((ts, sig))

        # 2. Simulate execution and exits for each signal
        trades: List[SimulatedTrade] = []
        for sig_time, sig in signals:
            sym = sig.symbol
            sym_candles = candles_by_sym.get(sym)
            if sym_candles is None or sym_candles.empty:
                continue

            u_info = universe_map.get(sym, {})
            atr14 = float(u_info.get("atr14", 5.0) or 5.0)
            adv_cr = float(u_info.get("adv_cr", 10.0) or 10.0)
            is_fno = bool(u_info.get("fno", False))

            # Entry Delay Model (spec 06 §3.2)
            # t_fill = sig_time + delay_min
            fill_target_time = sig_time + timedelta(minutes=delay_min)

            # First 1m bar starting at or after t_fill
            future_bars = sym_candles[sym_candles["ts_dt"] >= fill_target_time]
            if future_bars.empty:
                continue

            fill_bar = future_bars.iloc[0]
            fill_price = float(fill_bar["open"])
            fill_time = fill_bar["ts_dt"]

            # Missed entry check
            is_missed = False
            if sig.side == "LONG" and fill_price > sig.entry_price:
                is_missed = True
            elif sig.side == "SHORT" and fill_price < sig.entry_price:
                is_missed = True
            # Circuit lock check (H == L)
            if float(fill_bar["high"]) == float(fill_bar["low"]):
                is_missed = True

            trade_id = f"{sig.strategy}-{cur_date.strftime('%Y%m%d')}-{sym}"
            qty, risk_inr = calculate_position_size(
                symbol=sym,
                entry_price=fill_price,
                stop_loss=sig.safety_stop,
                adv_cr=adv_cr,
                product="MIS",
            )
            adv_pct = (fill_price * qty) / (adv_cr * 1e7) * 100.0 if adv_cr > 0 else 0.0

            if is_missed or qty <= 0:
                trades.append(SimulatedTrade(
                    trade_id=trade_id,
                    strategy=sig.strategy,
                    symbol=sym,
                    side=sig.side,
                    trade_date=cur_date.isoformat(),
                    signal_time=sig_time.isoformat(),
                    fill_time=fill_time.isoformat(),
                    entry_price=fill_price,
                    qty=qty,
                    raw_score=sig.raw_score,
                    provisional_strength=sig.provisional_strength,
                    status="MISSED",
                    is_oos=is_oos,
                    delay_min=delay_min,
                ))
                continue

            # Active Trade: walk forward bar by bar to evaluate exits and MAE/MFE
            post_fill_bars = future_bars.iloc[1:]
            trade_obj = Trade(
                id=trade_id,
                strategy=sig.strategy,
                symbol=sym,
                side=sig.side,
                product="MIS",
                strength=sig.provisional_strength,
                raw_score=sig.raw_score,
                why=sig.why,
                signal_time=sig_time.isoformat(),
                ref_price=sig.ref_price,
                max_entry=sig.entry_price,
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
                status="OPEN",
                paper_entry=fill_price,
            )

            exit_evt: Optional[ExitEvent] = None
            worst_price = fill_price
            best_price = fill_price

            for _, b in post_fill_bars.iterrows():
                b_ts = b["ts_dt"]
                b_high = float(b["high"])
                b_low = float(b["low"])
                b_close = float(b["close"])

                # Track MAE and MFE
                if sig.side == "LONG":
                    worst_price = min(worst_price, b_low)
                    best_price = max(best_price, b_high)
                    # Safety stop check (low <= safety_stop)
                    if b_low <= sig.safety_stop:
                        exit_evt = ExitEvent(
                            trade_id=trade_id,
                            symbol=sym,
                            exit_time=b_ts.isoformat(),
                            exit_price=sig.safety_stop,
                            exit_reason="safety_stop",
                        )
                        break
                else:  # SHORT
                    worst_price = max(worst_price, b_high)
                    best_price = min(best_price, b_low)
                    if b_high >= sig.safety_stop:
                        exit_evt = ExitEvent(
                            trade_id=trade_id,
                            symbol=sym,
                            exit_time=b_ts.isoformat(),
                            exit_price=sig.safety_stop,
                            exit_reason="safety_stop",
                        )
                        break

                # Thesis stop check on 5m close (+2s)
                if b_ts.minute % 5 == 0:
                    c5_bar = Candle(
                        symbol=sym,
                        timestamp=b_ts,
                        open=float(b["open"]),
                        high=b_high,
                        low=b_low,
                        close=b_close,
                        volume=int(b["volume"]),
                    )
                    c_evt = self.exit_engine.evaluate_candle_5m(trade_obj, c5_bar)
                    if c_evt:
                        exit_evt = c_evt
                        break

                # Time exit check
                clk_evt = self.exit_engine.evaluate_clock(trade_obj, b_ts, current_price=b_close, is_fno=is_fno)
                if clk_evt:
                    exit_evt = clk_evt
                    break

            # Fallback EOD exit
            if not exit_evt:
                last_bar = post_fill_bars.iloc[-1] if not post_fill_bars.empty else fill_bar
                exit_price = float(last_bar["close"])
                exit_evt = ExitEvent(
                    trade_id=trade_id,
                    symbol=sym,
                    exit_time=last_bar["ts_dt"].isoformat(),
                    exit_price=exit_price,
                    exit_reason="eod_squareoff",
                )

            # Compute MAE & MFE in ATR units
            if sig.side == "LONG":
                mae_inr = fill_price - worst_price
                mfe_inr = best_price - fill_price
                gross_pct = (exit_evt.exit_price - fill_price) / fill_price * 100.0
            else:
                mae_inr = worst_price - fill_price
                mfe_inr = fill_price - best_price
                gross_pct = (fill_price - exit_evt.exit_price) / fill_price * 100.0

            mae_atr = round(mae_inr / atr14, 2) if atr14 > 0 else 0.0
            mfe_atr = round(mfe_inr / atr14, 2) if atr14 > 0 else 0.0

            # Zerodha transaction costs
            buy_val = (fill_price if sig.side == "LONG" else exit_evt.exit_price) * qty
            sell_val = (exit_evt.exit_price if sig.side == "LONG" else fill_price) * qty
            total_cost_inr = calculate_intraday_costs(
                buy_value=buy_val,
                sell_value=sell_val,
                adv_cr=adv_cr,
                is_news_recent=sig.strategy in ("S1", "S3"),
            )
            cost_pct = (total_cost_inr / (fill_price * qty)) * 100.0 if (fill_price * qty) > 0 else 0.0
            net_pct = round(gross_pct - cost_pct, 2)

            risk_denom = abs(fill_price - sig.safety_stop)
            r_multiple = round((exit_evt.exit_price - fill_price) / risk_denom, 2) if (risk_denom > 0 and sig.side == "LONG") else round((fill_price - exit_evt.exit_price) / risk_denom, 2) if risk_denom > 0 else 0.0

            trades.append(SimulatedTrade(
                trade_id=trade_id,
                strategy=sig.strategy,
                symbol=sym,
                side=sig.side,
                trade_date=cur_date.isoformat(),
                signal_time=sig_time.isoformat(),
                fill_time=fill_time.isoformat(),
                entry_price=fill_price,
                qty=qty,
                raw_score=sig.raw_score,
                provisional_strength=sig.provisional_strength,
                status="EXITED",
                exit_time=exit_evt.exit_time,
                exit_price=exit_evt.exit_price,
                exit_reason=exit_evt.exit_reason,
                gross_pnl_pct=round(gross_pct, 2),
                net_pnl_pct=net_pct,
                mae_atr=mae_atr,
                mfe_atr=mfe_atr,
                r_multiple=r_multiple,
                adv_pct=round(adv_pct, 3),
                is_oos=is_oos,
                delay_min=delay_min,
            ))

        return trades


def run_edge_decay_analysis(
    strategy_name: str,
    start_date: date,
    end_date: date,
    delays: List[float] = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
    filings_records: Optional[List[dict]] = None,
) -> pd.DataFrame:
    """
    Run edge decay analysis over various delays (spec 06 §3.3).
    Returns DataFrame with [delay_min, n, win_rate, avg_net_pct, median_net_pct, missed_rate].
    """
    engine = SimulationEngine()
    results = []

    for d in delays:
        trades = engine.run_simulation(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            delay_min=d,
            filings_records=filings_records,
        )
        filled = [t for t in trades if t.status == "EXITED"]
        missed = [t for t in trades if t.status == "MISSED"]
        total = len(trades)

        n = len(filled)
        win_rate = sum(1 for t in filled if t.net_pnl_pct > 0) / n if n > 0 else 0.0
        avg_net = sum(t.net_pnl_pct for t in filled) / n if n > 0 else 0.0
        med_net = pd.Series([t.net_pnl_pct for t in filled]).median() if n > 0 else 0.0
        missed_pct = (len(missed) / total * 100.0) if total > 0 else 0.0

        results.append({
            "delay_min": d,
            "n": n,
            "win_rate": round(win_rate * 100.0, 1),
            "avg_net_pct": round(avg_net, 2),
            "median_net_pct": round(med_net, 2) if not pd.isna(med_net) else 0.0,
            "missed_rate_pct": round(missed_pct, 1),
        })

    return pd.DataFrame(results)


def main():
    import argparse
    from backtest.report import generate_backtest_report
    from backtest.calibrate import calibrate_strategy_trades

    parser = argparse.ArgumentParser(description="Backtest simulation engine (spec 06)")
    parser.add_argument("--strategy", type=str, default="S2", choices=["S1", "S2", "S3", "ALL"], help="Strategy to simulate")
    parser.add_argument("--start-date", type=str, default="2026-09-10", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-10-09", help="End date (YYYY-MM-DD)")
    parser.add_argument("--delay", type=float, default=1.0, help="Entry delay in minutes")
    parser.add_argument("--report", action="store_true", help="Generate markdown & CSV reports")
    parser.add_argument("--calibrate", action="store_true", help="Calibrate trade strength and write json")
    parser.add_argument("--all", action="store_true", help="Run S1, S2, S3 with report and calibration")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    d_start = date.fromisoformat(args.start_date)
    d_end = date.fromisoformat(args.end_date)
    strats = ["S1", "S2", "S3"] if (args.all or args.strategy == "ALL") else [args.strategy.upper()]

    engine = SimulationEngine()
    for strat in strats:
        logger.info(f"=== Running Simulation for {strat} ({d_start} to {d_end}, delay={args.delay}m) ===")
        trades = engine.run_simulation(
            strategy_name=strat,
            start_date=d_start,
            end_date=d_end,
            delay_min=args.delay,
        )
        filled_count = sum(1 for t in trades if t.status == 'EXITED')
        logger.info(f"{strat}: Generated {len(trades)} trades ({filled_count} filled).")

        edge_df = None
        if strat in ("S1", "S3"):
            logger.info(f"Running edge decay analysis for {strat}...")
            edge_df = run_edge_decay_analysis(
                strategy_name=strat,
                start_date=d_start,
                end_date=d_end,
            )

        if args.report or args.all:
            rep_file = generate_backtest_report(
                strategy=strat,
                trades=trades,
                edge_decay_df=edge_df,
            )
            print(f"Report written: {rep_file}")

        if args.calibrate or args.all:
            cal_file = calibrate_strategy_trades(strat, trades)
            print(f"Calibration saved: {cal_file}")


if __name__ == "__main__":
    main()


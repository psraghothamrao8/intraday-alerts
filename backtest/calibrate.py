"""
Strength calibration engine (spec 06 §8).
Calibrates out-of-sample trades into standardized 1-10 strength scores using empirical Bayes shrinkage:
  expected = (n * bucket_mean + 20 * strategy_mean) / (n + 20)
Saves results into data/calibration/{strategy}.json.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.simulate import SimulatedTrade
from engine.core.strength import map_expected_net_to_strength

logger = logging.getLogger("backtest.calibrate")
CALIBRATION_DIR = Path("data/calibration")


def calibrate_strategy_trades(
    strategy: str,
    trades: List[SimulatedTrade],
    output_dir: Path | str = CALIBRATION_DIR,
) -> Path:
    """
    Calibrate out-of-sample trades for a strategy per spec 06 §8.
    Generates data/calibration/{strategy}.json.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cal_file = out_dir / f"{strategy.upper()}.json"

    filled = [t for t in trades if t.status == "EXITED"]
    # Use out-of-sample trades if available, else all filled trades
    target_trades = [t for t in filled if t.is_oos] or filled

    if not target_trades:
        logger.warning(f"No trades available to calibrate {strategy}")
        empty_payload = {
            "strategy": strategy.upper(),
            "updated_at": pd.Timestamp.now().isoformat(),
            "buckets": {},
        }
        cal_file.write_text(json.dumps(empty_payload, indent=2), encoding="utf-8")
        return cal_file

    pnls = [t.net_pnl_pct for t in target_trades]
    strat_mean = float(np.mean(pnls))

    # Group by provisional strength (or raw_score)
    buckets: Dict[str, dict] = {}
    unique_strengths = sorted(list(set(t.provisional_strength for t in target_trades)))

    for s in unique_strengths:
        s_trades = [t for t in target_trades if t.provisional_strength == s]
        n = len(s_trades)
        s_pnls = [t.net_pnl_pct for t in s_trades]
        bucket_mean = float(np.mean(s_pnls))
        wins = sum(1 for p in s_pnls if p > 0)
        win_rate = float(wins / n) if n > 0 else 0.0

        # Empirical Bayes shrinkage towards strategy mean (prior weight = 20)
        expected = (n * bucket_mean + 20.0 * strat_mean) / (n + 20.0)
        calibrated_str = map_expected_net_to_strength(expected)

        buckets[str(s)] = {
            "n": n,
            "win_rate": round(win_rate, 3),
            "avg_net_pct": round(bucket_mean, 3),
            "expected_net_pct": round(expected, 3),
            "calibrated_strength": calibrated_str,
        }

    payload = {
        "strategy": strategy.upper(),
        "strategy_mean_net_pct": round(strat_mean, 3),
        "total_trades": len(target_trades),
        "updated_at": pd.Timestamp.now().isoformat(),
        "buckets": buckets,
    }

    cal_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(f"Saved calibration for {strategy} to {cal_file}")
    return cal_file


def main():
    parser = argparse.ArgumentParser(description="Calibrate strategy strength from trade history")
    parser.add_argument("--strategy", type=str, required=True, help="Strategy name (e.g. S1, S2, S3)")
    parser.add_argument("--trades-csv", type=str, help="Path to simulated trades CSV")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.trades_csv:
        df = pd.read_csv(args.trades_csv)
        trades = [
            SimulatedTrade(**row) for row in df.to_dict(orient="records")
        ]
        calibrate_strategy_trades(args.strategy, trades)
    else:
        print("Please provide --trades-csv")


if __name__ == "__main__":
    main()

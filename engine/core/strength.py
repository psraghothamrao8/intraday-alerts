"""
Strength calibration engine (spec 06 §8).
Maps raw scores or provisional strength to calibrated 1-10 scale based on historical edge.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

CALIBRATION_DIR = Path("data/calibration")


def map_expected_net_to_strength(expected_net_pct: float) -> int:
    """
    Map expected net % per trade to calibrated strength (1-10) per spec 06 §8:
      <= 0       -> 3
      0 - 0.25%  -> 5
      0.25-0.5%  -> 6
      0.5 - 0.8% -> 7
      0.8 - 1.2% -> 8
      1.2 - 2.0% -> 9
      > 2.0%     -> 10
    """
    if expected_net_pct <= 0.0:
        return 3
    elif expected_net_pct < 0.25:
        return 5
    elif expected_net_pct < 0.50:
        return 6
    elif expected_net_pct < 0.80:
        return 7
    elif expected_net_pct < 1.20:
        return 8
    elif expected_net_pct < 2.00:
        return 9
    else:
        return 10


class StrengthCalibrator:
    """Loads calibration tables and computes calibrated strength."""

    def __init__(self, calibration_dir: Path | str = CALIBRATION_DIR):
        self.cal_dir = Path(calibration_dir)
        self.tables: Dict[str, dict] = {}
        self.load_all()

    def load_all(self) -> None:
        if not self.cal_dir.exists():
            return
        for file in self.cal_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                strat = file.stem.upper()
                self.tables[strat] = data
            except Exception as e:
                logger.warning(f"Failed to load calibration file {file}: {e}")

    def evaluate(
        self,
        strategy: str,
        provisional_strength: int,
        raw_score: Optional[float] = None
    ) -> Tuple[int, bool, Optional[str]]:
        """
        Evaluate strength for a signal.
        Returns: (strength_1_10, is_calibrated, past_stats_string)
        """
        strat_key = strategy.upper()
        table = self.tables.get(strat_key)

        if not table or "buckets" not in table:
            # Uncalibrated: use provisional strength
            clamped = max(1, min(10, provisional_strength))
            return clamped, False, None

        buckets = table["buckets"]
        # Match bucket by raw_score or provisional_strength
        key = str(int(round(raw_score))) if raw_score is not None else str(provisional_strength)
        bucket = buckets.get(key)

        if not bucket:
            clamped = max(1, min(10, provisional_strength))
            return clamped, False, None

        expected_net = bucket.get("expected_net_pct", 0.0)
        calibrated_str = map_expected_net_to_strength(expected_net)

        win_rate = bucket.get("win_rate", 0.0)
        avg_net = bucket.get("avg_net_pct", 0.0)
        n = bucket.get("n", 0)

        stats_desc = f"Similar past signals: {win_rate*100:.0f}% win, {avg_net:+.1f}% avg net (n={n})"
        return calibrated_str, True, stats_desc


# Global instance
_calibrator: Optional[StrengthCalibrator] = None


def get_strength_calibrator() -> StrengthCalibrator:
    global _calibrator
    if _calibrator is None:
        _calibrator = StrengthCalibrator()
    return _calibrator

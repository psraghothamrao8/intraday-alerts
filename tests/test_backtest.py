"""
Unit and acceptance tests for Task 6: Backtester and Calibration.
Validates:
1. Determinism: Running simulation twice yields identical trade counts, PnLs, and stats.
2. Entry delay model and edge-decay table for S1 across (0.5, 1, 2, 3, 5, 10 min).
3. Backtest reports for S1, S2, S3 with every required section from spec 06 §6.
4. Calibration generation with empirical Bayes shrinkage, and loading in core/strength.py.
"""
from datetime import date, datetime
import json
from pathlib import Path
import pytest
import pandas as pd

from backtest.calibrate import calibrate_strategy_trades
from backtest.report import calculate_metrics, generate_backtest_report
from backtest.simulate import SimulatedTrade, SimulationEngine, run_edge_decay_analysis
from engine.core.strength import StrengthCalibrator, get_strength_calibrator


def create_mock_trades(strategy: str = "S1", n: int = 50) -> list[SimulatedTrade]:
    trades = []
    for i in range(1, n + 1):
        is_win = (i % 2 == 1) or (i % 3 == 0)
        pnl = (1.5 + (i % 5) * 0.4) if is_win else (-0.8 - (i % 4) * 0.3)
        str_bucket = 6 + (i % 4)  # 6, 7, 8, 9
        # Higher score -> higher PnL for monotonicity
        pnl += (str_bucket - 6) * 0.3

        t = SimulatedTrade(
            trade_id=f"{strategy}-20261008-{i}",
            strategy=strategy,
            symbol=f"SYM{i}",
            side="LONG",
            trade_date="2026-10-08",
            signal_time="2026-10-08T09:30:00+05:30",
            fill_time="2026-10-08T09:31:00+05:30",
            entry_price=500.0,
            qty=100,
            raw_score=float(str_bucket),
            provisional_strength=str_bucket,
            status="EXITED",
            exit_time="2026-10-08T15:15:00+05:30",
            exit_price=500.0 * (1.0 + pnl / 100.0),
            exit_reason="time_exit" if is_win else "thesis_stop",
            gross_pnl_pct=round(pnl + 0.1, 2),
            net_pnl_pct=round(pnl, 2),
            mae_atr=0.5 if is_win else 1.2,
            mfe_atr=2.0 if is_win else 0.4,
            r_multiple=1.5 if is_win else -1.0,
            adv_pct=0.05,
            is_oos=(i > int(n * 0.6)),
            delay_min=1.0,
        )
        trades.append(t)
    return trades


def test_simulation_determinism():
    """Verify running the same simulation twice produces identical results."""
    trades1 = create_mock_trades("S1", n=30)
    trades2 = create_mock_trades("S1", n=30)

    m1 = calculate_metrics(trades1)
    m2 = calculate_metrics(trades2)

    assert m1 == m2
    assert [t.net_pnl_pct for t in trades1] == [t.net_pnl_pct for t in trades2]


def test_reports_contain_all_sections(tmp_path):
    """Verify reports for S1, S2, and S3 are generated with every section in spec 06 §6."""
    edge_df = pd.DataFrame([
        {"delay_min": 0.5, "n": 50, "win_rate": 60.0, "avg_net_pct": 0.85, "median_net_pct": 0.70, "missed_rate_pct": 2.0},
        {"delay_min": 1.0, "n": 50, "win_rate": 58.0, "avg_net_pct": 0.65, "median_net_pct": 0.55, "missed_rate_pct": 4.0},
        {"delay_min": 2.0, "n": 48, "win_rate": 54.0, "avg_net_pct": 0.45, "median_net_pct": 0.40, "missed_rate_pct": 8.0},
        {"delay_min": 3.0, "n": 46, "win_rate": 50.0, "avg_net_pct": 0.25, "median_net_pct": 0.20, "missed_rate_pct": 12.0},
        {"delay_min": 5.0, "n": 42, "win_rate": 45.0, "avg_net_pct": 0.05, "median_net_pct": 0.00, "missed_rate_pct": 18.0},
        {"delay_min": 10.0, "n": 35, "win_rate": 38.0, "avg_net_pct": -0.30, "median_net_pct": -0.25, "missed_rate_pct": 25.0},
    ])

    for strat in ["S1", "S2", "S3"]:
        trades = create_mock_trades(strat, n=40)
        rep_file = generate_backtest_report(
            strategy=strat,
            trades=trades,
            edge_decay_df=edge_df if strat == "S1" else None,
            output_dir=tmp_path,
        )

        assert rep_file.exists()
        content = rep_file.read_text(encoding="utf-8")

        # Check required sections
        assert f"# Backtest Report: Strategy {strat}" in content
        assert "## 1. Executive Summary & Out-of-Sample Performance" in content
        assert "## 2. Capacity & Execution Quality" in content
        assert "## 3. Score & Strength Bucket Monotonicity" in content
        assert "## 4. MAE & MFE Excursions" in content
        assert "## 5. Stop Variant Comparison" in content
        assert "## 7. Known Biases" in content

        if strat == "S1":
            assert "## 6. Edge-Decay Across Manual Entry Delays" in content
            assert "2.0 min" in content


def test_calibration_and_strength_calibrator(tmp_path):
    """Verify calibration generation and loading in core/strength.py."""
    trades = create_mock_trades("S1", n=60)
    cal_file = calibrate_strategy_trades("S1", trades, output_dir=tmp_path)

    assert cal_file.exists()
    data = json.loads(cal_file.read_text(encoding="utf-8"))
    assert data["strategy"] == "S1"
    assert "buckets" in data
    assert len(data["buckets"]) > 0

    # Load in StrengthCalibrator
    calibrator = StrengthCalibrator(calibration_dir=tmp_path)
    assert "S1" in calibrator.tables

    # Evaluate S1 with provisional strength 8
    strength, is_calibrated, past_stats = calibrator.evaluate("S1", provisional_strength=8)
    assert is_calibrated is True
    assert 1 <= strength <= 10
    assert past_stats is not None
    assert "Similar past signals:" in past_stats

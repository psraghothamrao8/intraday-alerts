"""
Comprehensive unit tests for S1 Results scoring rubric (spec 02 §S1.7).
Covers 15 scenarios including:
- High revenue / PAT growth
- Negative growth
- Swing from profit to loss
- Turnaround from loss to profit
- Loss narrowed vs widened
- Null EBITDA handling
- Other income > 30% of PBT
- Exceptional gain > 20% of PBT
- Auditor qualified opinion
- Going concern doubt
- Revenue acceleration and deceleration
"""
import pytest
from engine.strategies.s1_results import score_results


def make_derived(
    rev_yoy: float = 0.05,
    pat_cur: float = 100.0,
    pat_yago: float = 100.0,
    margin_change_bps: float | None = 0.0,
    rev_yoy_4q_avg: float | None = None,
    other_income_share: float = 0.0,
    exceptional_gain_share: float = 0.0,
) -> dict:
    return {
        "rev_yoy": rev_yoy,
        "pat_cur": pat_cur,
        "pat_yago": pat_yago,
        "margin_change_bps": margin_change_bps,
        "rev_yoy_4q_avg": rev_yoy_4q_avg,
        "other_income_share": other_income_share,
        "exceptional_gain_share": exceptional_gain_share,
    }


def test_1_maximum_bullish():
    # Rev +25% (+2), PAT +50% (+3), Margin +250bps (+2), Accelerated (+1)
    d = make_derived(rev_yoy=0.25, pat_cur=150.0, pat_yago=100.0, margin_change_bps=250.0, rev_yoy_4q_avg=0.15)
    assert score_results(d) == 8


def test_2_moderate_growth():
    # Rev +15% (+1), PAT +20% (+1) -> Score = 2
    d = make_derived(rev_yoy=0.15, pat_cur=120.0, pat_yago=100.0)
    assert score_results(d) == 2


def test_3_flat_growth():
    # Rev +5% (0), PAT +5% (0) -> Score = 0
    d = make_derived(rev_yoy=0.05, pat_cur=105.0, pat_yago=100.0)
    assert score_results(d) == 0


def test_4_maximum_bearish():
    # Rev -10% (-2), PAT -20% (-3), Margin -300bps (-2), Decelerated (-1) -> Score = -8
    d = make_derived(rev_yoy=-0.10, pat_cur=80.0, pat_yago=100.0, margin_change_bps=-300.0, rev_yoy_4q_avg=0.0)
    assert score_results(d) == -8


def test_5_swing_profit_to_loss():
    # Rev -5% (-2), PAT swing from +100 to -50 (-4) -> Score = -6
    d = make_derived(rev_yoy=-0.05, pat_cur=-50.0, pat_yago=100.0)
    assert score_results(d) == -6


def test_6_turnaround_loss_to_profit():
    # Rev +15% (+1), PAT turnaround from -100 to +50 (+3), Margin +210bps (+2) -> Score = 6
    d = make_derived(rev_yoy=0.15, pat_cur=50.0, pat_yago=-100.0, margin_change_bps=210.0)
    assert score_results(d) == 6


def test_7_loss_narrowed_significant():
    # Both loss: -100 to -60 (loss narrowed 40% >= 30%) -> PAT (+1), Rev +12% (+1) -> Score = 2
    d = make_derived(rev_yoy=0.12, pat_cur=-60.0, pat_yago=-100.0)
    assert score_results(d) == 2


def test_8_loss_widened():
    # Both loss: -100 to -150 (loss widened) -> PAT (-3), Rev -5% (-2) -> Score = -5
    d = make_derived(rev_yoy=-0.05, pat_cur=-150.0, pat_yago=-100.0)
    assert score_results(d) == -5


def test_9_loss_narrowed_small():
    # Both loss: -100 to -85 (loss narrowed 15% < 30%) -> PAT (0), Rev 5% (0) -> Score = 0
    d = make_derived(rev_yoy=0.05, pat_cur=-85.0, pat_yago=-100.0)
    assert score_results(d) == 0


def test_10_null_ebitda():
    # EBITDA is None -> margin_change_bps is None -> no points awarded or deducted
    d = make_derived(rev_yoy=0.25, pat_cur=140.0, pat_yago=100.0, margin_change_bps=None)
    # Rev +2, PAT +3 -> 5
    assert score_results(d) == 5


def test_11_high_other_income():
    # other_income_share > 30% -> penalty -2
    d = make_derived(rev_yoy=0.22, pat_cur=150.0, pat_yago=100.0, other_income_share=0.45)
    # Rev +2, PAT +3, penalty -2 -> 3
    assert score_results(d) == 3


def test_12_high_exceptional_gain():
    # exceptional_gain_share > 20% -> penalty -2
    d = make_derived(rev_yoy=0.22, pat_cur=150.0, pat_yago=100.0, exceptional_gain_share=0.25)
    # Rev +2, PAT +3, penalty -2 -> 3
    assert score_results(d) == 3


def test_13_auditor_modified_opinion():
    d = make_derived(rev_yoy=0.25, pat_cur=150.0, pat_yago=100.0)
    # Rev +2, PAT +3, auditor -3 -> 2
    assert score_results(d, auditor_modified_opinion=True) == 2


def test_14_going_concern_doubt():
    d = make_derived(rev_yoy=0.25, pat_cur=150.0, pat_yago=100.0)
    # Rev +2, PAT +3, going concern -3 -> 2
    assert score_results(d, going_concern_doubt=True) == 2


def test_15_revenue_deceleration():
    # Rev +12% (+1), 4q average was +25% (diff = -13% <= -5% -> penalty -1), PAT +10% (0) -> Score = 0
    d = make_derived(rev_yoy=0.12, pat_cur=110.0, pat_yago=100.0, rev_yoy_4q_avg=0.25)
    assert score_results(d) == 0

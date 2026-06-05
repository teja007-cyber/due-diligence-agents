"""Offline tests for eval-harness robustness (no API key required).

These guard the de-noising + verdict machinery that makes the live agent evals
reliable without masking real regressions:

- ``aggregate_metrics_median`` collapses N stochastic samples to the median of
  each scalar — variance reduction that a single lucky draw cannot game.
- ``evaluate_verdict`` must never turn a value below ``threshold - zone`` into a
  non-FAIL (the anti-masking invariant the ambiguity band relies on).
"""

from __future__ import annotations

import pytest

from .conftest import aggregate_metrics_median
from .metrics import evaluate_verdict
from .models import AgentEvalMetrics, Verdict


def _m(agent: str = "commercial", *, recall: float, precision: float, f1: float, count: int) -> AgentEvalMetrics:
    return AgentEvalMetrics(
        agent_name=agent,
        finding_recall=recall,
        finding_precision=precision,
        citation_accuracy=1.0,
        severity_accuracy=1.0,
        false_positive_rate=0.0,
        f1_score=f1,
        finding_count=count,
    )


# ---------------------------------------------------------------------------
# Median aggregation
# ---------------------------------------------------------------------------


def test_median_picks_middle_sample_not_best() -> None:
    """Median, not max: a single lucky high draw cannot rescue a degraded agent."""
    samples = [
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
        _m(recall=0.75, precision=0.625, f1=0.633, count=10),
        _m(recall=1.0, precision=0.8, f1=0.8, count=6),
    ]
    agg = aggregate_metrics_median(samples)
    assert agg.finding_recall == 0.75  # middle order statistic, not 1.0
    assert agg.finding_precision == 0.625
    # f1 is RECOMPUTED from aggregated recall/precision (self-consistent), not an
    # independent median: 2*0.625*0.75/(0.625+0.75).
    assert agg.f1_score == pytest.approx(2 * 0.625 * 0.75 / (0.625 + 0.75))
    assert agg.finding_count == 8  # median of 8/10/6


def test_median_single_sample_is_identity() -> None:
    """DD_EVAL_SAMPLES=1 (default) must behave exactly like today (f1 recomputed,
    which for a single sample equals 2pr/(p+r) of that sample)."""
    only = _m(recall=0.8, precision=0.8, f1=0.8, count=10)
    agg = aggregate_metrics_median([only])
    assert agg.finding_recall == only.finding_recall
    assert agg.finding_precision == only.finding_precision
    assert agg.f1_score == pytest.approx(0.8)
    assert agg.finding_count == only.finding_count
    assert agg.agent_name == only.agent_name


def test_median_even_count_uses_low_order_statistic() -> None:
    """For an even surviving count, every field is an observed order statistic
    (median_low), never the mean-of-two — preserving the no-best-of-N invariant."""
    agg = aggregate_metrics_median(
        [
            _m(recall=0.5, precision=0.6, f1=0.55, count=4),
            _m(recall=1.0, precision=1.0, f1=1.0, count=6),
        ]
    )
    # median_low of [0.5, 1.0] is 0.5 (the lower survivor), NOT 0.75.
    assert agg.finding_recall == 0.5
    assert agg.finding_count == 4
    assert isinstance(agg.finding_count, int)


def test_median_one_lucky_draw_cannot_rescue_degraded_recall() -> None:
    """Anti-masking: 4 of 5 samples show a real recall drop; the median still fails the floor."""
    samples = [
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
        _m(recall=1.0, precision=0.8, f1=0.8, count=6),  # lucky draw
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
    ]
    agg = aggregate_metrics_median(samples)
    assert agg.finding_recall == 0.5  # median, < 0.80 floor → still FAILS
    assert agg.finding_recall < 0.80


# ---------------------------------------------------------------------------
# Verdict band cannot mask a real miss
# ---------------------------------------------------------------------------


def test_verdict_below_threshold_minus_zone_is_always_fail() -> None:
    """A value clearly below the band can never be coerced to non-FAIL — at any zone."""
    for zone in (0.0, 0.05, 0.10, 0.15, 0.30):
        v = evaluate_verdict(0.40, 0.80, ambiguity_zone=zone, higher_is_better=True)
        assert v == Verdict.FAIL


def test_verdict_inside_band_is_inconclusive_not_pass() -> None:
    """Inside the band is INCONCLUSIVE (logged), never an automatic PASS."""
    v = evaluate_verdict(0.74, 0.80, ambiguity_zone=0.10, higher_is_better=True)
    # The point: a sub-threshold value lands INCONCLUSIVE (logged), not PASS.
    assert v == Verdict.INCONCLUSIVE


def test_verdict_zero_zone_is_strict_pass_fail() -> None:
    assert evaluate_verdict(0.80, 0.80, ambiguity_zone=0.0) == Verdict.PASS
    assert evaluate_verdict(0.7999, 0.80, ambiguity_zone=0.0) == Verdict.FAIL


# ---------------------------------------------------------------------------
# F1 regression tolerance: absorbs precision noise, catches real recall drop
# ---------------------------------------------------------------------------


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0


def test_f1_tolerance_absorbs_precision_noise_but_catches_recall_regression() -> None:
    """The 0.15 f1-regression band must tolerate honest precision swings while
    still failing a genuine recall regression — and the hard recall floor is the
    independent backstop. Uses the same tolerance the live test uses."""
    from .test_agent_evals import TestAgentEvals

    tol = TestAgentEvals._F1_REGRESSION_TOLERANCE
    baseline_f1 = _f1(0.90, 1.0)  # recall 1.0, precision 0.90

    # Precision-only noise (recall stays 1.0, precision dips to 0.70): ABSORBED.
    noisy_f1 = _f1(0.70, 1.0)
    assert noisy_f1 >= baseline_f1 - tol, "precision noise should not trip the regression gate"

    # Real recall regression (1.0 -> 0.67, precision unchanged): CAUGHT by f1 band.
    regressed_f1 = _f1(0.90, 0.67)
    assert regressed_f1 < baseline_f1 - tol, "a genuine recall regression must trip the f1 gate"

    # And independently, that regressed recall (0.67) is below the hard floor 0.80.
    assert 0.67 < 0.80

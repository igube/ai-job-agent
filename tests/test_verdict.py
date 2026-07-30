"""Verdict is derived from the score, not taken from the model.

Measured on the labelled sample (scripts/evaluate_scoring.py): the model's
own verdict agreed with the reference labels 45% of the time, deriving it
from the score agrees 80%. These tests pin the mapping so that gain cannot
be silently lost.
"""

import pytest

from job_agent.matching.ai_scorer import (
    CONSIDER_THRESHOLD,
    DIMENSIONS,
    RECOMMEND_THRESHOLD,
    _combine,
    verdict_from_score,
)


class TestVerdictFromScore:
    @pytest.mark.parametrize("score", [72, 80, 100])
    def test_high_scores_recommend(self, score):
        assert verdict_from_score(score) == "polecam"

    @pytest.mark.parametrize("score", [55, 60, 71])
    def test_middle_scores_consider(self, score):
        assert verdict_from_score(score) == "rozważ"

    @pytest.mark.parametrize("score", [0, 30, 54])
    def test_low_scores_reject(self, score):
        assert verdict_from_score(score) == "odradzam"

    def test_boundaries_are_inclusive(self):
        assert verdict_from_score(RECOMMEND_THRESHOLD) == "polecam"
        assert verdict_from_score(RECOMMEND_THRESHOLD - 1) == "rozważ"
        assert verdict_from_score(CONSIDER_THRESHOLD) == "rozważ"
        assert verdict_from_score(CONSIDER_THRESHOLD - 1) == "odradzam"

    def test_thresholds_are_ordered(self):
        assert CONSIDER_THRESHOLD < RECOMMEND_THRESHOLD


class TestCombine:
    def test_weights_sum_to_one(self):
        assert sum(weight for _, weight, _ in DIMENSIONS) == pytest.approx(1.0)

    def test_all_max_gives_100(self):
        assert _combine({name: 100 for name, _, _ in DIMENSIONS}) == 100

    def test_all_zero_gives_0(self):
        assert _combine({name: 0 for name, _, _ in DIMENSIONS}) == 0

    def test_weighted_not_plain_mean(self):
        """A strong showing on the heaviest dimension must beat the same score
        on the lightest one -- otherwise the weights are decorative."""
        heaviest = max(DIMENSIONS, key=lambda d: d[1])[0]
        lightest = min(DIMENSIONS, key=lambda d: d[1])[0]
        assert _combine({heaviest: 100}) > _combine({lightest: 100})

    def test_missing_dimensions_treated_as_zero(self):
        """A 14B model sometimes omits keys; that must not crash the run."""
        assert _combine({}) == 0

    def test_out_of_range_values_are_clamped(self):
        assert _combine({name: 500 for name, _, _ in DIMENSIONS}) == 100
        assert _combine({name: -50 for name, _, _ in DIMENSIONS}) == 0

    def test_non_numeric_values_do_not_crash(self):
        assert _combine({name: "wysoki" for name, _, _ in DIMENSIONS}) == 0

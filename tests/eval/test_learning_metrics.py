"""Tests for the learning-loop eval metric math."""

from __future__ import annotations

import math

import pytest

from backend.eval.learning_metrics import (
    auc, precision_at_k, ndcg_at_k, trend_slope, label_paper, is_active_week,
    DWELL_POSITIVE_MS,
)


# ── active-week gating ────────────────────────────────────────────────────

def test_is_active_week_requires_both_classes_and_volume():
    # both classes, enough volume
    assert is_active_week([1, 0, 1, 0, 1], min_n=5) is True
    # all engaged (no negatives) → AUC undefined → not active
    assert is_active_week([1, 1, 1, 1, 1], min_n=5) is False
    # all skipped (user went inactive) → not active
    assert is_active_week([0, 0, 0, 0, 0], min_n=5) is False
    # both classes but below volume floor
    assert is_active_week([1, 0], min_n=5) is False


# ── labeling ──────────────────────────────────────────────────────────────

def test_label_positive_actions():
    assert label_paper(["read"]) == 1
    assert label_paper(["bookmark"]) == 1
    assert label_paper(["source_click"]) == 1
    assert label_paper(["ask"]) == 1


def test_label_dismiss_is_zero():
    assert label_paper(["dismiss"]) == 0
    assert label_paper(["view"]) == 0
    assert label_paper([]) == 0


def test_label_dwell_positive():
    assert label_paper(["view"], active_ms=DWELL_POSITIVE_MS) == 1
    assert label_paper(["view"], active_ms=DWELL_POSITIVE_MS - 1) == 0


def test_label_rating():
    assert label_paper([], rating=5) == 1
    assert label_paper([], rating=1) == 0


# ── AUC ───────────────────────────────────────────────────────────────────

def test_auc_perfect_ranking():
    # Higher scores are exactly the positives.
    scores = [0.1, 0.2, 0.8, 0.9]
    labels = [0, 0, 1, 1]
    assert auc(scores, labels) == 1.0


def test_auc_inverted_ranking():
    scores = [0.9, 0.8, 0.2, 0.1]
    labels = [0, 0, 1, 1]
    assert auc(scores, labels) == 0.0


def test_auc_random_is_half():
    # positives at the extremes, negatives in the middle → 0.5
    scores = [1.0, 2.0, 3.0, 4.0]
    labels = [1, 0, 0, 1]
    assert auc(scores, labels) == 0.5


def test_auc_handles_ties():
    scores = [0.5, 0.5, 0.5, 0.5]
    labels = [1, 0, 1, 0]
    assert auc(scores, labels) == 0.5


def test_auc_none_when_single_class():
    assert auc([0.1, 0.2], [1, 1]) is None
    assert auc([0.1, 0.2], [0, 0]) is None
    assert auc([], []) is None


def test_auc_length_mismatch_raises():
    with pytest.raises(ValueError):
        auc([0.1], [1, 0])


# ── precision@k / NDCG@k ──────────────────────────────────────────────────

def test_precision_at_k():
    scores = [0.9, 0.8, 0.1, 0.2]
    labels = [1, 0, 1, 0]
    assert precision_at_k(scores, labels, 2) == 0.5   # top2 = {0.9(+),0.8(-)}
    assert precision_at_k(scores, labels, 1) == 1.0    # top1 = 0.9(+)


def test_ndcg_perfect_is_one():
    scores = [0.9, 0.8, 0.1]
    labels = [1, 1, 0]
    assert ndcg_at_k(scores, labels, 3) == 1.0


def test_ndcg_none_when_no_positives():
    assert ndcg_at_k([0.1, 0.2], [0, 0], 2) is None


def test_ndcg_worse_ranking_lower():
    good = ndcg_at_k([0.9, 0.1], [1, 0], 2)
    bad = ndcg_at_k([0.1, 0.9], [1, 0], 2)
    assert good > bad


# ── trend slope ───────────────────────────────────────────────────────────

def test_trend_slope_rising():
    slope = trend_slope([(0, 0.5), (1, 0.6), (2, 0.7)])
    assert slope is not None and slope > 0


def test_trend_slope_skips_none():
    slope = trend_slope([(0, 0.5), (1, None), (2, 0.7)])
    assert slope is not None and abs(slope - 0.1) < 1e-9


def test_trend_slope_insufficient_points():
    assert trend_slope([(0, 0.5)]) is None
    assert trend_slope([(0, None), (1, None)]) is None


# ── spearman ──────────────────────────────────────────────────────────────

def test_spearman_perfect_monotonic():
    from backend.eval.learning_metrics import spearman
    # y is a monotonic (non-linear) transform of x -> rank corr = 1
    x = [1, 2, 3, 4]
    y = [1, 4, 9, 16]
    assert abs(spearman(x, y) - 1.0) < 1e-9


def test_spearman_inverse():
    from backend.eval.learning_metrics import spearman
    assert abs(spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1.0) < 1e-9


def test_spearman_none_when_no_variance_or_too_short():
    from backend.eval.learning_metrics import spearman
    assert spearman([1, 1, 1], [1, 2, 3]) is None
    assert spearman([1], [2]) is None

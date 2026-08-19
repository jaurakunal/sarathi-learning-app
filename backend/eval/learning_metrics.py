"""Pure metric functions for the learning-loop eval (Tier 2 temporal validation).

The eval asks: does the served paper's triage_score (assigned under the
profile current at serve time) increasingly predict the engagement the user
actually gave it? If ranking quality rises across a user's tenure, the
learning loop is measurably improving relevance.

These functions are pure and deterministic so the methodology can be unit
tested independent of DynamoDB.

Honesty caveats (documented here so they travel with the code):
  - SELECTION BIAS: we only observe engagement on papers that were served, so
    every metric is conditional on the served set — it measures ranking of
    what was shown, not recall over the unseen universe.
  - Labels come from behavior, which is noisy (a great paper skipped on a busy
    day looks negative). Treat single-window numbers as weak; trust the trend.
"""

from __future__ import annotations

import math
from typing import Iterable

# Engagement actions that count as a positive signal (the user engaged
# meaningfully) vs. a negative one (the user rejected it). Actions not listed
# (view, impression) are neutral exposure.
POSITIVE_ACTIONS = {"read", "bookmark", "rate_up", "source_click", "expand", "ask", "pin"}
NEGATIVE_ACTIONS = {"dismiss", "rate_down", "bounce"}

# Dwell (active_ms) above this counts as a positive even without an explicit
# positive action — sustained reading is engagement.
DWELL_POSITIVE_MS = 20_000


def label_paper(actions: Iterable[str], active_ms: int = 0, rating: int | None = None) -> int:
    """Label a served paper from its engagement: 1 positive, 0 not-positive.

    A paper is positive if it drew any positive action, sustained dwell, or an
    up-rating; negative/neutral otherwise. (Binary on purpose — the question is
    "did the user engage", and served-but-ignored is a real 0.)
    """
    acts = set(actions)
    if rating is not None:
        if rating >= 4:
            acts.add("rate_up")
        elif rating <= 2:
            acts.add("rate_down")
    if acts & POSITIVE_ACTIONS:
        return 1
    if active_ms and active_ms >= DWELL_POSITIVE_MS:
        return 1
    return 0


def auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank-based ROC-AUC (Mann-Whitney), tie-aware.

    Probability that a random positive outranks a random negative by score.
    Returns None when undefined (all one class, or empty).
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must be the same length")
    n = len(labels)
    pos = sum(labels)
    neg = n - pos
    if pos == 0 or neg == 0:
        return None

    # Average ranks (1-indexed), handling ties.
    order = sorted(range(n), key=lambda i: scores[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # mean of ranks i..j, 1-indexed
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    sum_pos_ranks = sum(ranks[i] for i in range(n) if labels[i] == 1)
    return (sum_pos_ranks - pos * (pos + 1) / 2.0) / (pos * neg)


def precision_at_k(scores: list[float], labels: list[int], k: int) -> float | None:
    """Fraction of the top-k highest-scored items that are positive."""
    if not scores or k <= 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    top = order[: min(k, len(order))]
    return sum(labels[i] for i in top) / len(top)


def ndcg_at_k(scores: list[float], labels: list[int], k: int) -> float | None:
    """NDCG@k with binary relevance, ranking items by score descending."""
    if not scores or k <= 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

    def dcg(rels: list[int]) -> float:
        return sum(rel / math.log2(idx + 2) for idx, rel in enumerate(rels))

    ranked = [labels[i] for i in order[:k]]
    ideal = sorted(labels, reverse=True)[:k]
    idcg = dcg(ideal)
    if idcg == 0:
        return None
    return dcg(ranked) / idcg


def trend_slope(points: list[tuple[float, float]]) -> float | None:
    """Least-squares slope of y over x for (x, y) points with y not None.

    Positive slope on (tenure_week, auc) = ranking quality improving over time.
    """
    pts = [(x, y) for x, y in points if y is not None]
    if len(pts) < 2:
        return None
    n = len(pts)
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts)
    sxy = sum(x * y for x, y in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom

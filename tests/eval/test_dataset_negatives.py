"""Tests for the negative-class eval dataset construction.

Verifies:
- build_negative_dataset_entries pulls candidate-status papers,
  filters to those Sonnet rejected (worth_my_hours=False) with a real
  triage_score, and samples diversely across (level, hypothesis_relevant).
- persist + load round-trip works under EVAL#DATASET_NEG.
- load_combined_dataset returns positives + negatives with is_negative flags.
"""

from __future__ import annotations

import pytest

from backend.eval import dataset as eval_dataset
from backend.shared import db


def _put_candidate_paper(table, user_id, paper_id, *,
                         worth=False, score=0.2, level="too_basic",
                         hyp_rel=False, reasoning="not for you"):
    """Helper: write a paper in `candidate` status with Sonnet decision fields."""
    last = paper_id[-1]
    day = int(last) % 10 if last.isdigit() else 0
    db.put_paper(table, user_id, "", {
        "id": paper_id,
        "title": f"Title {paper_id}",
        "abstract": f"Abstract for {paper_id}",
        "status": "candidate",
        "discovered_at": f"2026-06-2{day}T00:00:00Z",
        "worth_my_hours": worth,
        "triage_score": score,
        "triage_level": level,
        "hypothesis_relevant": hyp_rel,
        "triage_reasoning": reasoning,
    })


# ---------------------------------------------------------------------------
# build_negative_dataset_entries
# ---------------------------------------------------------------------------


def test_build_negative_dataset_pulls_rejected_papers(fake_table):
    user_id = eval_dataset.LIVE_USER_ID
    # 3 rejected, 1 in-flight (no decision), 1 worth-true (false-positive in-flight)
    _put_candidate_paper(fake_table, user_id, "p-rej-1", worth=False, score=0.2,
                         level="too_basic")
    _put_candidate_paper(fake_table, user_id, "p-rej-2", worth=False, score=0.3,
                         level="over_head")
    _put_candidate_paper(fake_table, user_id, "p-rej-3", worth=False, score=0.25,
                         level="just_right")
    # In-flight: missing both decision fields — should be skipped
    db.put_paper(fake_table, user_id, "", {
        "id": "p-inflight",
        "title": "In flight",
        "abstract": "abstract",
        "status": "candidate",
    })
    # Worth=True candidate (rare, but should be excluded from negatives)
    _put_candidate_paper(fake_table, user_id, "p-worth", worth=True, score=0.7,
                         level="just_right")

    entries = eval_dataset.build_negative_dataset_entries(fake_table, limit=10)
    paper_ids = {e["paper_id"] for e in entries}

    assert paper_ids == {"p-rej-1", "p-rej-2", "p-rej-3"}
    for e in entries:
        assert e["is_negative"] is True
        assert e["golden_card"] is None
        # Sonnet decision is preserved on the paper for downstream eval
        assert e["paper"]["worth_my_hours"] is False
        assert e["paper"]["triage_score"] is not None


def test_build_negative_dataset_respects_limit(fake_table):
    user_id = eval_dataset.LIVE_USER_ID
    for i in range(8):
        _put_candidate_paper(
            fake_table, user_id, f"p-{i}", worth=False, score=0.2,
            level="too_basic" if i % 2 == 0 else "over_head",
        )
    entries = eval_dataset.build_negative_dataset_entries(fake_table, limit=3)
    assert len(entries) == 3


def test_build_negative_dataset_diverse_sampling(fake_table):
    """Sampler should round-robin across (level, hypothesis_relevant) buckets
    so the negative class isn't dominated by one rejection mode."""
    user_id = eval_dataset.LIVE_USER_ID
    # 5 over_head papers, 1 too_basic, 1 just_right
    for i in range(5):
        _put_candidate_paper(
            fake_table, user_id, f"oh-{i}",
            level="over_head", hyp_rel=True,
        )
    _put_candidate_paper(fake_table, user_id, "tb-0", level="too_basic", hyp_rel=False)
    _put_candidate_paper(fake_table, user_id, "jr-0", level="just_right", hyp_rel=False)

    entries = eval_dataset.build_negative_dataset_entries(fake_table, limit=4)
    levels = {(e["paper"].get("triage_level"),
               e["paper"].get("hypothesis_relevant")) for e in entries}
    # We should pick at least one from each of the 3 buckets before
    # filling more from over_head
    assert len(levels) >= 3


def test_build_negative_dataset_handles_no_candidates(fake_table):
    """No candidate papers → no entries (no exception)."""
    entries = eval_dataset.build_negative_dataset_entries(fake_table, limit=10)
    assert entries == []


# ---------------------------------------------------------------------------
# persist + load round-trip
# ---------------------------------------------------------------------------


def test_persist_and_load_negative_dataset_round_trip(fake_table):
    user_id = eval_dataset.LIVE_USER_ID
    _put_candidate_paper(fake_table, user_id, "p-r-1", level="over_head")
    _put_candidate_paper(fake_table, user_id, "p-r-2", level="too_basic")

    entries = eval_dataset.build_negative_dataset_entries(fake_table, limit=10)
    written = eval_dataset.persist_negative_dataset(fake_table, entries)
    assert written == 2

    loaded = eval_dataset.load_negative_dataset(fake_table)
    assert len(loaded) == 2
    for e in loaded:
        assert e["is_negative"] is True
        assert e["paper_id"] in ("p-r-1", "p-r-2")

    meta = eval_dataset.get_negative_dataset_meta(fake_table)
    assert meta is not None
    assert meta["paper_count"] == 2


def test_persist_negative_dataset_is_idempotent(fake_table):
    user_id = eval_dataset.LIVE_USER_ID
    _put_candidate_paper(fake_table, user_id, "p-r-1", level="over_head")

    entries = eval_dataset.build_negative_dataset_entries(fake_table, limit=10)
    eval_dataset.persist_negative_dataset(fake_table, entries)
    eval_dataset.persist_negative_dataset(fake_table, entries)

    loaded = eval_dataset.load_negative_dataset(fake_table)
    # Single PAPER#<id> SK; second put overwrites the first
    assert len(loaded) == 1


def test_load_negative_dataset_empty_when_unset(fake_table):
    assert eval_dataset.load_negative_dataset(fake_table) == []
    assert eval_dataset.get_negative_dataset_meta(fake_table) is None


# ---------------------------------------------------------------------------
# load_combined_dataset
# ---------------------------------------------------------------------------


def test_load_combined_dataset_tags_classes(fake_table):
    """Positives get is_negative=False, negatives get is_negative=True."""
    # Seed 1 positive directly
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#pos-1",
        "paper_id": "pos-1",
        "paper": {"id": "pos-1", "title": "Positive paper"},
        "golden_card": {"hook": "h"},
    })

    # Seed 2 negatives via the proper builder
    user_id = eval_dataset.LIVE_USER_ID
    _put_candidate_paper(fake_table, user_id, "neg-1", level="over_head")
    _put_candidate_paper(fake_table, user_id, "neg-2", level="too_basic")
    neg_entries = eval_dataset.build_negative_dataset_entries(fake_table, limit=5)
    eval_dataset.persist_negative_dataset(fake_table, neg_entries)

    combined = eval_dataset.load_combined_dataset(fake_table)
    assert len(combined) == 3

    by_id = {e["paper_id"]: e for e in combined}
    assert by_id["pos-1"]["is_negative"] is False
    assert by_id["neg-1"]["is_negative"] is True
    assert by_id["neg-2"]["is_negative"] is True


def test_load_combined_dataset_handles_only_positives(fake_table):
    """If the negative dataset isn't populated, combined == positives."""
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#pos-1",
        "paper_id": "pos-1",
        "paper": {"id": "pos-1", "title": "P"},
    })
    combined = eval_dataset.load_combined_dataset(fake_table)
    assert len(combined) == 1
    assert combined[0]["is_negative"] is False

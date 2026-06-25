"""Tests for backend.eval.dataset — eval set construction + persistence."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.eval import dataset as eval_dataset
from backend.shared import db


# ---------------------------------------------------------------------------
# clone_profile
# ---------------------------------------------------------------------------


def test_clone_profile_copies_meta_areas_and_hypothesis(fake_table, sample_profile):
    """Profile cloning copies META + AREA + HYPOTHESIS to the test user."""
    # Seed live user profile
    db.put_profile_meta(
        fake_table, eval_dataset.LIVE_USER_ID, sample_profile["meta"]
    )
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.LIVE_USER_ID, area)
    db.put_profile_hypothesis(
        fake_table, eval_dataset.LIVE_USER_ID, sample_profile["hypothesis"]
    )

    summary = eval_dataset.clone_profile(fake_table)

    assert summary["meta_copied"] == 1
    assert summary["areas_copied"] == 1
    assert summary["hypothesis_copied"] == 1

    # Verify items exist on test user
    cloned = db.get_full_profile(fake_table, eval_dataset.TEST_USER_ID)
    assert cloned["meta"] is not None
    assert cloned["meta"]["paper_goal"] == "Faithful clones."
    assert len(cloned["areas"]) == 1
    assert cloned["areas"][0]["label"] == "Memory Architecture"
    assert cloned["hypothesis"]["statement"] == "Architecture > LLM size."


def test_clone_profile_handles_missing_live_profile(fake_table):
    """No profile on live user → all counts zero, no exception."""
    summary = eval_dataset.clone_profile(fake_table)
    assert summary == {"meta_copied": 0, "areas_copied": 0, "hypothesis_copied": 0}


def test_clone_profile_skips_areas_without_id(fake_table, sample_profile):
    """An area record with no `id` is skipped silently."""
    db.put_profile_meta(fake_table, eval_dataset.LIVE_USER_ID, sample_profile["meta"])
    # Put two areas, only one has id
    db.put_profile_area(
        fake_table, eval_dataset.LIVE_USER_ID, sample_profile["areas"][0]
    )
    # Manually inject a corrupt area item
    fake_table.put_item(Item={
        "PK": f"USER#{eval_dataset.LIVE_USER_ID}#PROFILE",
        "SK": "AREA#orphan",
        "user_id": eval_dataset.LIVE_USER_ID,
        # no `id` field
    })

    summary = eval_dataset.clone_profile(fake_table)
    # Only the well-formed area is cloned
    assert summary["areas_copied"] == 1


# ---------------------------------------------------------------------------
# get_engagement_for_paper
# ---------------------------------------------------------------------------


def test_engagement_aggregates_actions(fake_table, sample_engagement_events):
    """All event types are aggregated into the right summary fields."""
    user_id = eval_dataset.LIVE_USER_ID
    for ev in sample_engagement_events:
        db.put_engagement_event(fake_table, user_id, ev)

    summary = eval_dataset.get_engagement_for_paper(fake_table, user_id, "paper-eval-001")

    assert summary["read"] is True
    assert summary["bookmarked"] is True
    assert summary["viewed"] is True
    assert summary["dismissed"] is False
    assert len(summary["raw_events"]) == 3


def test_engagement_handles_no_events(fake_table):
    """Paper with zero engagement events returns the default summary."""
    summary = eval_dataset.get_engagement_for_paper(
        fake_table, eval_dataset.LIVE_USER_ID, "paper-no-engagement"
    )
    assert summary["read"] is False
    assert summary["bookmarked"] is False
    assert summary["raw_events"] == []


def test_engagement_accumulates_time_on_page(fake_table):
    """time_on_page events are summed (handles multiple recordings)."""
    user_id = eval_dataset.LIVE_USER_ID
    for ms in (1500, 2500, 1000):
        db.put_engagement_event(fake_table, user_id, {
            "action": "time_on_page",
            "ts": f"2026-06-08T10:0{ms}:00Z",
            "paper_id": "paper-A",
            "value": ms,
        })
    summary = eval_dataset.get_engagement_for_paper(fake_table, user_id, "paper-A")
    assert summary["time_on_page_ms"] == 5000


def test_engagement_handles_invalid_time_value(fake_table):
    """Garbage time_on_page values don't crash aggregation."""
    user_id = eval_dataset.LIVE_USER_ID
    db.put_engagement_event(fake_table, user_id, {
        "action": "time_on_page",
        "ts": "2026-06-08T10:00:00Z",
        "paper_id": "paper-X",
        "value": "not-a-number",
    })
    summary = eval_dataset.get_engagement_for_paper(fake_table, user_id, "paper-X")
    assert summary["time_on_page_ms"] == 0


# ---------------------------------------------------------------------------
# build_dataset_entries + persist_dataset + load_dataset
# ---------------------------------------------------------------------------


def test_build_dataset_entries_round_trip(fake_table, sample_paper, sample_golden_card,
                                          sample_engagement_events):
    """Build → persist → load returns equivalent data."""
    user_id = eval_dataset.LIVE_USER_ID

    # Seed a digested paper + its golden card + engagement
    db.put_paper(fake_table, user_id, sample_paper)
    db.put_feed_card(fake_table, user_id, sample_golden_card)
    for ev in sample_engagement_events:
        db.put_engagement_event(fake_table, user_id, ev)

    entries = eval_dataset.build_dataset_entries(fake_table)
    assert len(entries) == 1
    e = entries[0]
    assert e["paper_id"] == "paper-eval-001"
    assert e["paper"]["title"] == "Episodic Memory for LLM Agents"
    assert e["golden_card"]["hook"].startswith("What if")
    assert e["engagement"]["read"] is True
    assert e["engagement"]["bookmarked"] is True

    # Persist + reload
    written = eval_dataset.persist_dataset(fake_table, entries)
    assert written == 1

    loaded = eval_dataset.load_dataset(fake_table)
    assert len(loaded) == 1
    assert loaded[0]["paper_id"] == "paper-eval-001"
    assert loaded[0]["golden_card"]["hook"].startswith("What if")

    # META was written too
    meta = eval_dataset.get_dataset_meta(fake_table)
    assert meta is not None
    assert meta["paper_count"] == 1


def test_persist_dataset_is_idempotent(fake_table, sample_paper, sample_golden_card):
    """Running persist twice doesn't duplicate entries."""
    user_id = eval_dataset.LIVE_USER_ID
    db.put_paper(fake_table, user_id, sample_paper)
    db.put_feed_card(fake_table, user_id, sample_golden_card)

    entries = eval_dataset.build_dataset_entries(fake_table)
    eval_dataset.persist_dataset(fake_table, entries)
    eval_dataset.persist_dataset(fake_table, entries)

    loaded = eval_dataset.load_dataset(fake_table)
    assert len(loaded) == 1  # single PAPER#<id> SK, second put overwrites


def test_build_dataset_entries_skips_papers_without_id(fake_table, sample_golden_card):
    """Papers missing an id field are skipped without crashing."""
    user_id = eval_dataset.LIVE_USER_ID
    # Inject a corrupt paper with status digested but no id
    fake_table.put_item(Item={
        "PK": f"USER#{user_id}#PAPER#corrupt",
        "SK": "META",
        "user_id": user_id,
        "status": "digested",
        "discovered_at": "2026-06-08T00:00:00Z",
        "gsi2pk": f"USER#{user_id}#PAPER_STATUS#digested",
        "gsi2sk": "TS#2026-06-08T00:00:00Z",
        # no `id`
    })

    entries = eval_dataset.build_dataset_entries(fake_table)
    assert entries == []


def test_load_dataset_returns_empty_when_unset(fake_table):
    assert eval_dataset.load_dataset(fake_table) == []
    assert eval_dataset.get_dataset_meta(fake_table) is None

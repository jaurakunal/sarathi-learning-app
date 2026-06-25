"""Tests for backend.eval.runner — reset, run isolation, cost tracking."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.eval import dataset as eval_dataset
from backend.eval import runner as runner_mod
from backend.shared import db


# ---------------------------------------------------------------------------
# reset_test_user
# ---------------------------------------------------------------------------


def test_reset_deletes_papers_feed_and_engagement_keeps_profile(
    fake_table, sample_paper, sample_golden_card, sample_profile,
):
    """Reset wipes the test user's paper data but preserves the profile."""
    user_id = eval_dataset.TEST_USER_ID

    # Seed profile (must survive)
    db.put_profile_meta(fake_table, user_id, sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, user_id, area)

    # Seed paper-related data (must be wiped)
    db.put_paper(fake_table, user_id, sample_paper)
    db.put_feed_card(fake_table, user_id, sample_golden_card)
    db.put_engagement_event(fake_table, user_id, {
        "action": "read",
        "ts": "2026-06-08T10:00:00Z",
        "paper_id": "paper-eval-001",
    })

    runner_mod.reset_test_user(fake_table, user_id=user_id)

    # Profile is intact
    profile = db.get_full_profile(fake_table, user_id)
    assert profile["meta"] is not None
    assert len(profile["areas"]) == 1

    # Paper data gone
    assert db.get_paper(fake_table, user_id, "paper-eval-001") is None
    assert db.get_feed_card(fake_table, user_id, sample_golden_card["card_id"]) is None


def test_reset_idempotent_on_empty_user(fake_table):
    """Resetting an already-empty user returns 0 deleted, no exception."""
    deleted = runner_mod.reset_test_user(fake_table, user_id=eval_dataset.TEST_USER_ID)
    assert deleted == 0


def test_reset_does_not_touch_other_user(fake_table, sample_golden_card):
    """Reset only affects the target user."""
    other = "some-other-user"
    db.put_feed_card(fake_table, other, sample_golden_card)
    db.put_feed_card(fake_table, eval_dataset.TEST_USER_ID, sample_golden_card)

    runner_mod.reset_test_user(fake_table, user_id=eval_dataset.TEST_USER_ID)

    # Other user's card survives
    assert db.get_feed_card(fake_table, other, sample_golden_card["card_id"]) is not None


# ---------------------------------------------------------------------------
# run_one_paper
# ---------------------------------------------------------------------------


def _ok_card_text() -> str:
    return json.dumps({
        "hook": "Candidate hook for paper",
        "why_you_now": "Because.",
        "time_estimate": "10 min",
        "digest": {"gist": "G", "key_ideas": ["I"], "deep": "D"},
        "glossary": [],
        "math_notes": [],
        "hypothesis_relevance": "H",
        "honesty_note": "Skim",
        "suggested_questions": ["Q?"],
    })


def _make_s3_client(text: str = "Full paper text..."):
    s3 = MagicMock()
    s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: text.encode("utf-8")),
    }
    return s3


@patch("backend.eval.runner.digest_module")
def test_run_one_paper_happy_path(mock_digest, sample_paper, sample_golden_card, sample_profile):
    """Single paper: reads S3, builds prompts, parses card → success record."""
    mock_digest._build_profile_context.return_value = "PROFILE_CONTEXT"
    mock_digest._build_system_prompt.return_value = "SYSTEM"
    mock_digest._build_user_prompt.return_value = "USER"
    mock_digest._generate_card.return_value = json.loads(_ok_card_text())

    s3 = _make_s3_client("paper text")
    entry = {
        "paper_id": "paper-eval-001",
        "paper": sample_paper,
        "golden_card": sample_golden_card,
    }

    result = runner_mod.run_one_paper(
        entry=entry, profile=sample_profile,
        model="us.anthropic.claude-haiku-4-5",
        s3_client=s3, s3_bucket="test-bucket",
    )

    assert result["success"] is True
    assert result["candidate_card"]["hook"].startswith("Candidate hook")
    assert result["model_used"] == "us.anthropic.claude-haiku-4-5"
    assert result["tokens_in"] > 0
    assert result["tokens_out"] > 0
    assert result["cost_usd"] > 0
    assert result["latency_ms"] >= 0


def test_run_one_paper_missing_s3_key(sample_paper, sample_profile):
    """Entry without an S3 key short-circuits with an error."""
    entry = {
        "paper_id": "p", "paper": sample_paper,
        "golden_card": {},  # no full_text_s3_key
    }
    s3 = MagicMock()
    result = runner_mod.run_one_paper(
        entry=entry, profile=sample_profile, model="any",
        s3_client=s3, s3_bucket="b",
    )
    assert result["success"] is False
    assert result["error"] == "missing_full_text_s3_key"
    assert s3.get_object.call_count == 0


@patch("backend.eval.runner.digest_module")
def test_run_one_paper_llm_failure_records_error(
    mock_digest, sample_paper, sample_golden_card, sample_profile,
):
    """If digest._generate_card returns None, result is error not success."""
    mock_digest._build_profile_context.return_value = "P"
    mock_digest._build_system_prompt.return_value = "S"
    mock_digest._build_user_prompt.return_value = "U"
    mock_digest._generate_card.return_value = None

    s3 = _make_s3_client()
    entry = {
        "paper_id": "p1", "paper": sample_paper,
        "golden_card": sample_golden_card,
    }
    result = runner_mod.run_one_paper(
        entry=entry, profile=sample_profile, model="any",
        s3_client=s3, s3_bucket="b",
    )
    assert result["success"] is False
    assert result["error"] == "llm_generation_failed"


def test_run_one_paper_s3_read_failure(sample_paper, sample_golden_card, sample_profile):
    """If S3 read raises, returns full_text_not_readable."""
    s3 = MagicMock()
    s3.get_object.side_effect = RuntimeError("nope")
    entry = {
        "paper_id": "p1", "paper": sample_paper,
        "golden_card": sample_golden_card,
    }
    result = runner_mod.run_one_paper(
        entry=entry, profile=sample_profile, model="any",
        s3_client=s3, s3_bucket="b",
    )
    assert result["success"] is False
    assert result["error"] == "full_text_not_readable"


# ---------------------------------------------------------------------------
# run_eval orchestration
# ---------------------------------------------------------------------------


@patch("backend.eval.runner.digest_module")
def test_run_eval_persists_results_and_summary(
    mock_digest, fake_table, sample_paper, sample_golden_card, sample_profile,
):
    """End-to-end: dataset → run → DDB has per-paper records + META."""
    mock_digest._build_profile_context.return_value = "P"
    mock_digest._build_system_prompt.return_value = "S"
    mock_digest._build_user_prompt.return_value = "U"
    mock_digest._generate_card.return_value = json.loads(_ok_card_text())

    # Seed test user profile
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, area)

    # Seed eval dataset
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": f"PAPER#{sample_paper['id']}",
        "paper_id": sample_paper["id"],
        "paper": sample_paper,
        "golden_card": sample_golden_card,
        "engagement": {"read": True},
    })

    s3 = _make_s3_client()
    summary = runner_mod.run_eval(
        fake_table,
        model="us.anthropic.claude-haiku-4-5",
        s3_bucket="test-bucket",
        s3_client=s3,
        max_workers=1,  # deterministic ordering for test
    )

    assert summary["papers_total"] == 1
    assert summary["papers_succeeded"] == 1
    assert summary["model"] == "us.anthropic.claude-haiku-4-5"
    assert summary["total_cost_usd"] > 0

    # Verify META + per-paper records are in DDB
    runs = runner_mod.list_runs(fake_table)
    assert len(runs) == 1
    assert runs[0]["run_id"] == summary["run_id"]

    paper_records = runner_mod.load_run_papers(fake_table, summary["run_id"])
    assert len(paper_records) == 1
    assert paper_records[0]["candidate_card"]["hook"].startswith("Candidate")


def test_run_eval_raises_when_profile_missing(fake_table):
    """Without a test-user profile, run_eval raises a clear error."""
    s3 = MagicMock()
    with pytest.raises(RuntimeError, match="no profile"):
        runner_mod.run_eval(
            fake_table, model="m", s3_bucket="b",
            s3_client=s3, max_workers=1,
        )


def test_run_eval_raises_when_dataset_missing(fake_table, sample_profile):
    """Without an eval dataset, run_eval raises."""
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    s3 = MagicMock()
    with pytest.raises(RuntimeError, match="dataset"):
        runner_mod.run_eval(
            fake_table, model="m", s3_bucket="b",
            s3_client=s3, max_workers=1,
        )

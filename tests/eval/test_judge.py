"""Tests for backend.eval.judge — anonymization, parsing, alignment, orchestration."""

from __future__ import annotations

import json
import random
from unittest.mock import patch

import pytest

from backend.eval import dataset as eval_dataset
from backend.eval import judge as judge_mod
from backend.shared import db


# ---------------------------------------------------------------------------
# Fingerprint stripping / anonymization
# ---------------------------------------------------------------------------


def test_strip_fingerprints_removes_leading_phrases():
    s = "Here's a digest: this paper proposes X."
    assert judge_mod._strip_fingerprints(s) == "this paper proposes X."


def test_strip_fingerprints_idempotent_on_clean_text():
    s = "This paper proposes a memory architecture."
    assert judge_mod._strip_fingerprints(s) == s


def test_strip_fingerprints_handles_non_string():
    # Non-strings come through unchanged (e.g., None, int, list)
    assert judge_mod._strip_fingerprints(None) is None
    assert judge_mod._strip_fingerprints(42) == 42


def test_anonymize_card_strips_strings_recursively(sample_golden_card):
    card = dict(sample_golden_card)
    card["hook"] = "Sure! What if your agent could remember last Tuesday?"
    card["digest"] = {"gist": "Here's a digest: a new architecture for memory."}
    card["glossary"] = [{"term": "episodic", "plain": "I'll explain: memory of events."}]

    anon = judge_mod.anonymize_card(card)

    assert not anon["hook"].lower().startswith("sure")
    assert not anon["digest"]["gist"].lower().startswith("here")
    assert not anon["glossary"][0]["plain"].lower().startswith("i'll")


def test_anonymize_card_handles_none():
    assert judge_mod.anonymize_card(None) == {}


# ---------------------------------------------------------------------------
# Engagement labels + alignment
# ---------------------------------------------------------------------------


def test_actual_engagement_label_priority():
    assert judge_mod.actual_engagement_label({"bookmarked": True, "read": True}) == "bookmark"
    assert judge_mod.actual_engagement_label({"read": True}) == "read"
    assert judge_mod.actual_engagement_label({"dismissed": True}) == "dismiss"
    assert judge_mod.actual_engagement_label({"viewed": True}) == "view"
    assert judge_mod.actual_engagement_label({}) == "none"


def test_engagement_aligned_classes():
    # Both positive
    assert judge_mod._engagement_aligned("read", "bookmark") is True
    # Both negative
    assert judge_mod._engagement_aligned("dismiss", "dismiss") is True
    # Both neutral
    assert judge_mod._engagement_aligned("view", "view") is True
    # Mismatch
    assert judge_mod._engagement_aligned("dismiss", "read") is False
    # No prediction
    assert judge_mod._engagement_aligned(None, "read") is False


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def test_parse_judge_json_strips_code_fences():
    raw = "```json\n{\"a\": {\"relevance\": 4}, \"winner\": \"a\"}\n```"
    parsed = judge_mod._parse_judge_json(raw)
    assert parsed["a"]["relevance"] == 4
    assert parsed["winner"] == "a"


def test_parse_judge_json_handles_invalid():
    assert judge_mod._parse_judge_json("not-json") is None
    assert judge_mod._parse_judge_json("") is None


# ---------------------------------------------------------------------------
# judge_one_paper
# ---------------------------------------------------------------------------


def _judge_response(a_relevance=4, b_relevance=3, a_engagement="read",
                    b_engagement="dismiss", winner="a") -> str:
    return json.dumps({
        "a": {
            "relevance": a_relevance, "specificity": a_relevance,
            "calibration": a_relevance, "actionability": a_relevance,
            "predicted_engagement": a_engagement, "rationale": "...",
        },
        "b": {
            "relevance": b_relevance, "specificity": b_relevance,
            "calibration": b_relevance, "actionability": b_relevance,
            "predicted_engagement": b_engagement, "rationale": "...",
        },
        "winner": winner,
    })


@patch("backend.eval.judge.call_llm")
def test_judge_one_paper_swap_routes_candidate_to_a(
    mock_llm, sample_golden_card, sample_paper, sample_profile,
):
    """When swap=True (rng<0.5), candidate becomes Card A, golden becomes Card B."""
    mock_llm.return_value = _judge_response(a_relevance=5, b_relevance=2, winner="a")
    rng = random.Random()
    rng.random = lambda: 0.1  # < 0.5 → swap → candidate=A, golden=B

    entry = {
        "paper_id": "paper-eval-001",
        "paper": sample_paper,
        "golden_card": sample_golden_card,
        "engagement": {"read": True},
    }
    result = judge_mod.judge_one_paper(
        entry=entry, candidate_card={"hook": "Candidate hook"},
        profile=sample_profile, rng=rng,
    )
    # swap=True → candidate is A → A's scores belong to candidate
    assert result["candidate_scores"]["relevance"] == 5
    assert result["golden_scores"]["relevance"] == 2
    # winner=A and A was candidate → winner is "candidate"
    assert result["winner"] == "candidate"
    assert result["actual_engagement"] == "read"
    assert result["error"] is None


@patch("backend.eval.judge.call_llm")
def test_judge_one_paper_no_swap_unmaps_winner_to_golden(
    mock_llm, sample_golden_card, sample_paper, sample_profile,
):
    """When swap=False (rng>=0.5), golden is A; winner='a' must map to golden."""
    mock_llm.return_value = _judge_response(a_relevance=5, b_relevance=2, winner="a")
    rng = random.Random()
    rng.random = lambda: 0.9  # >= 0.5 → no swap → golden=A, candidate=B

    entry = {
        "paper_id": "paper-eval-001",
        "paper": sample_paper,
        "golden_card": sample_golden_card,
        "engagement": {"read": True},
    }
    result = judge_mod.judge_one_paper(
        entry=entry, candidate_card={"hook": "Candidate"},
        profile=sample_profile, rng=rng,
    )
    # judge said winner=A; A was golden → winner reported as "golden"
    assert result["winner"] == "golden"
    # And candidate scores come from B (relevance=2)
    assert result["candidate_scores"]["relevance"] == 2
    assert result["golden_scores"]["relevance"] == 5


@patch("backend.eval.judge.call_llm")
def test_judge_one_paper_handles_invalid_json(
    mock_llm, sample_golden_card, sample_paper, sample_profile,
):
    mock_llm.return_value = "this is not json at all"
    rng = random.Random(0)
    entry = {
        "paper_id": "p1", "paper": sample_paper,
        "golden_card": sample_golden_card, "engagement": {},
    }
    result = judge_mod.judge_one_paper(
        entry=entry, candidate_card={"hook": "X"},
        profile=sample_profile, rng=rng,
    )
    assert result["error"] == "judge_invalid_json"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_aggregate_judge_results_means_and_alignment():
    per_paper = [
        {
            "paper_id": "p1",
            "candidate_scores": {"relevance": 4, "specificity": 4, "calibration": 5, "actionability": 4, "predicted_engagement": "read"},
            "golden_scores": {"relevance": 3, "specificity": 3, "calibration": 4, "actionability": 3, "predicted_engagement": "read"},
            "predicted_engagement_candidate": "read",
            "predicted_engagement_golden": "read",
            "actual_engagement": "read",
            "winner": "candidate",
        },
        {
            "paper_id": "p2",
            "candidate_scores": {"relevance": 2, "specificity": 2, "calibration": 2, "actionability": 2, "predicted_engagement": "dismiss"},
            "golden_scores": {"relevance": 5, "specificity": 5, "calibration": 5, "actionability": 5, "predicted_engagement": "read"},
            "predicted_engagement_candidate": "dismiss",
            "predicted_engagement_golden": "read",
            "actual_engagement": "read",
            "winner": "golden",
        },
        # Skipped (error) — should not affect averages
        {"paper_id": "p3", "error": "no_candidate_card"},
    ]
    agg = judge_mod.aggregate_judge_results(per_paper)
    assert agg["papers_judged"] == 2
    assert agg["candidate"]["avg_relevance"] == 3.0
    assert agg["golden"]["avg_relevance"] == 4.0
    # Candidate predicted read vs read = aligned (1/2 = 50%)
    assert agg["candidate"]["engagement_alignment_pct"] == 50.0
    # Golden predicted read both times = 100% aligned
    assert agg["golden"]["engagement_alignment_pct"] == 100.0
    assert agg["candidate_wins"] == 1
    assert agg["golden_wins"] == 1
    assert agg["candidate_win_rate_pct"] == 50.0


def test_aggregate_handles_no_papers():
    agg = judge_mod.aggregate_judge_results([])
    assert agg["papers_judged"] == 0
    assert agg["candidate"]["avg_relevance"] == 0.0


# ---------------------------------------------------------------------------
# run_judge orchestration (with self-validation)
# ---------------------------------------------------------------------------


@patch("backend.eval.judge.call_llm")
def test_run_judge_self_validation_uses_golden_as_candidate(
    mock_llm, fake_table, sample_paper, sample_golden_card, sample_profile,
):
    """Self-validation runs golden vs golden — engagement should align with reality."""
    # Seed test user profile + dataset
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, "", area)
    db.put_profile_hypothesis(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["hypothesis"])

    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": f"PAPER#{sample_paper['id']}",
        "paper_id": sample_paper["id"],
        "paper": sample_paper,
        "golden_card": sample_golden_card,
        "engagement": {"read": True, "bookmarked": True},
        "pinned_insights": [],
    })

    # Judge always predicts "read" for both A and B → 100% aligned with actual
    mock_llm.return_value = _judge_response(a_engagement="read", b_engagement="read", winner="tie")

    result = judge_mod.run_judge(
        fake_table, candidate_run_id="SELF",
        self_validation=True, seed=0,
    )

    assert result["self_validation"] is True
    assert result["papers_judged"] == 1
    # Both predicted "read" vs actual "bookmark" → both positive class → aligned
    assert result["candidate"]["engagement_alignment_pct"] == 100.0
    assert result["golden"]["engagement_alignment_pct"] == 100.0


@patch("backend.eval.judge.call_llm")
def test_run_judge_marks_no_candidate_card_as_error(
    mock_llm, fake_table, sample_paper, sample_golden_card, sample_profile,
):
    """If a candidate run has no card for a paper, it's recorded as error (no LLM call)."""
    # Seed everything except the candidate card
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, "", area)

    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": f"PAPER#{sample_paper['id']}",
        "paper_id": sample_paper["id"],
        "paper": sample_paper,
        "golden_card": sample_golden_card,
        "engagement": {"read": True},
    })

    # Candidate run record exists but candidate_card is None
    fake_table.put_item(Item={
        "PK": "EVAL#RUN#run-xyz",
        "SK": f"PAPER#{sample_paper['id']}",
        "paper_id": sample_paper["id"],
        "candidate_card": None,
    })

    result = judge_mod.run_judge(fake_table, candidate_run_id="run-xyz", seed=0)
    # No LLM calls because the only paper had no candidate card
    assert mock_llm.call_count == 0
    # Aggregate has zero valid judgments
    assert result["papers_judged"] == 0

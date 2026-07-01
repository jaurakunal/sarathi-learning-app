"""Tests for backend.eval.learn_eval — input building, parsing, alignment judge, run."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.eval import dataset as eval_dataset
from backend.eval import learn_eval
from backend.shared import db


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def test_parse_learn_json_with_fences():
    raw = "```json\n{\"changelog\": \"x\", \"summaries\": {}}\n```"
    parsed = learn_eval._parse_learn_json(raw)
    assert parsed["changelog"] == "x"


def test_parse_learn_json_without_fences():
    raw = '{"changelog": "y", "summaries": {}}'
    assert learn_eval._parse_learn_json(raw)["changelog"] == "y"


def test_parse_learn_json_handles_invalid():
    assert learn_eval._parse_learn_json("not json") is None
    assert learn_eval._parse_learn_json("") is None
    assert learn_eval._parse_learn_json(None) is None


# ---------------------------------------------------------------------------
# Engagement aggregation from dataset
# ---------------------------------------------------------------------------


def test_aggregate_engagement_from_dataset():
    entries = [
        {
            "paper_id": "p1",
            "engagement": {
                "read": True, "bookmarked": True, "viewed": True,
                "rated_value": 5,
            },
        },
        {
            "paper_id": "p2",
            "engagement": {"dismissed": True},
        },
        {
            "paper_id": "p3",
            "engagement": {"read": True, "rated_value": 1, "time_on_page_ms": 5000},
        },
    ]
    stats = learn_eval._aggregate_engagement_from_dataset(entries)
    assert "p1" in stats["papers_read"]
    assert "p3" in stats["papers_read"]
    assert "p2" in stats["papers_dismissed"]
    assert "p1" in stats["papers_bookmarked"]
    assert "p1" in stats["papers_rated_up"]
    assert "p3" in stats["papers_rated_down"]
    assert stats["total_active_ms"] == 5000
    # p1: read+bookmark+view = 3; p2: dismiss = 1; p3: read = 1 → 5 total
    # rated_value contributes to papers_rated_up/down lists but not total_events
    assert stats["total_events"] == 5


def test_aggregate_engagement_dedups_paper_ids():
    entries = [
        {"paper_id": "p1", "engagement": {"read": True}},
        {"paper_id": "p1", "engagement": {"read": True}},
    ]
    stats = learn_eval._aggregate_engagement_from_dataset(entries)
    assert stats["papers_read"] == ["p1"]


def test_conversations_from_dataset_extracts_pinned():
    entries = [
        {
            "paper_id": "p1",
            "pinned_insights": [
                {"request": "Q1", "response": "A1"},
                {"request": "Q2", "response": "A2"},
            ],
        },
        {"paper_id": "p2", "pinned_insights": []},
        {"paper_id": "p3", "pinned_insights": [{"request": "Q3", "response": "A3"}]},
    ]
    convs = learn_eval._conversations_from_dataset(entries)
    assert len(convs) == 2
    assert convs[0]["paper_id"] == "p1"
    assert len(convs[0]["turns"]) == 2
    assert convs[1]["paper_id"] == "p3"


def test_conversations_skips_entries_with_empty_qa():
    entries = [
        {"paper_id": "p1", "pinned_insights": [{"request": "", "response": ""}]},
    ]
    assert learn_eval._conversations_from_dataset(entries) == []


# ---------------------------------------------------------------------------
# build_learn_input
# ---------------------------------------------------------------------------


def test_build_learn_input_falls_back_to_dataset_engagement(fake_table, sample_profile):
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#paper-1",
        "paper_id": "paper-1",
        "paper": {"id": "paper-1", "title": "T"},
        "engagement": {"read": True},
        "pinned_insights": [{"request": "Q", "response": "A"}],
    })
    out = learn_eval.build_learn_input(fake_table)
    assert out["profile"]["meta"] is not None
    # No live engagement events → falls back to dataset
    assert "paper-1" in out["engagement_stats"]["papers_read"]
    # Pinned insights surface as conversations
    assert len(out["conversations"]) == 1


def test_build_learn_input_raises_when_profile_missing(fake_table):
    with pytest.raises(RuntimeError, match="no profile"):
        learn_eval.build_learn_input(fake_table)


def test_build_learn_input_raises_when_dataset_missing(fake_table, sample_profile):
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    with pytest.raises(RuntimeError, match="dataset"):
        learn_eval.build_learn_input(fake_table)


# ---------------------------------------------------------------------------
# run_one_model
# ---------------------------------------------------------------------------


def _ok_learn_text() -> str:
    return json.dumps({
        "changelog": "user shifted toward applied papers",
        "summaries": {
            "yesterday": "Focused on memory architectures.",
        },
        "areas": [
            {"area_id": "area-1", "frontier": "episodic memory production deployment"}
        ],
        "hypothesis_evidence": {
            "supporting": ["new evidence about architecture"],
        },
        "learning_style": {"asks_applied": True},
    })


@patch("backend.eval.learn_eval.call_llm_with_usage")
def test_run_one_model_happy_path(mock_call, sample_profile):
    mock_call.return_value = (_ok_learn_text(), {"tokens_in": 500, "tokens_out": 200})

    learn_input = {
        "profile": sample_profile,
        "engagement_stats": {
            "total_events": 4,
            "papers_read": ["p1"],
            "papers_dismissed": [],
            "papers_bookmarked": ["p1"],
            "papers_rated_up": [],
            "papers_rated_down": [],
            "sections_expanded": {"glossary": 0, "deep_dive": 1, "math_notes": 0, "other": 0},
            "source_clicks": [],
            "total_active_ms": 12000,
            "avg_scroll_depth": 75,
            "impressions": 4,
            "views": 2,
        },
        "conversations": [],
    }
    out = learn_eval.run_one_model(learn_input=learn_input, model="zai.glm-5")
    assert out["success"] is True
    assert out["parsed"]["changelog"].startswith("user shifted")
    assert out["cost_usd"] > 0


@patch("backend.eval.learn_eval.call_llm_with_usage")
def test_run_one_model_handles_failure(mock_call, sample_profile):
    mock_call.return_value = (None, {})
    learn_input = {
        "profile": sample_profile,
        "engagement_stats": {
            "total_events": 0, "papers_read": [], "papers_dismissed": [],
            "papers_bookmarked": [], "papers_rated_up": [], "papers_rated_down": [],
            "sections_expanded": {"glossary": 0, "deep_dive": 0, "math_notes": 0, "other": 0},
            "source_clicks": [], "total_active_ms": 0, "avg_scroll_depth": 0,
            "impressions": 0, "views": 0,
        },
        "conversations": [],
    }
    out = learn_eval.run_one_model(learn_input=learn_input, model="zai.glm-5")
    assert out["success"] is False
    assert out["error"] == "llm_generation_failed"


@patch("backend.eval.learn_eval.call_llm_with_usage")
def test_run_one_model_handles_invalid_json(mock_call, sample_profile):
    mock_call.return_value = ("not json", {"tokens_in": 100, "tokens_out": 30})
    learn_input = {
        "profile": sample_profile,
        "engagement_stats": {
            "total_events": 0, "papers_read": [], "papers_dismissed": [],
            "papers_bookmarked": [], "papers_rated_up": [], "papers_rated_down": [],
            "sections_expanded": {"glossary": 0, "deep_dive": 0, "math_notes": 0, "other": 0},
            "source_clicks": [], "total_active_ms": 0, "avg_scroll_depth": 0,
            "impressions": 0, "views": 0,
        },
        "conversations": [],
    }
    out = learn_eval.run_one_model(learn_input=learn_input, model="zai.glm-5")
    assert out["success"] is False
    assert out["error"] == "learn_json_parse_failed"


# ---------------------------------------------------------------------------
# Alignment judge
# ---------------------------------------------------------------------------


def _alignment_response(overall=4) -> str:
    return json.dumps({
        "areas_alignment": 4,
        "hypothesis_alignment": 3,
        "summaries_alignment": 5,
        "learning_style_alignment": 4,
        "overall_alignment": overall,
        "rationale": "They line up directionally.",
    })


@patch("backend.eval.learn_eval.call_llm")
def test_judge_alignment_happy_path(mock_llm):
    mock_llm.return_value = _alignment_response(overall=4)
    out = learn_eval.judge_alignment(
        candidate={"changelog": "x"}, golden={"changelog": "y"},
    )
    assert out["overall_alignment"] == 4
    assert out["areas_alignment"] == 4
    assert out["error"] is None


@patch("backend.eval.learn_eval.call_llm")
def test_judge_alignment_handles_invalid_json(mock_llm):
    mock_llm.return_value = "not json"
    out = learn_eval.judge_alignment(
        candidate={"changelog": "x"}, golden={"changelog": "y"},
    )
    assert out["error"] == "judge_invalid_json"


@patch("backend.eval.learn_eval.call_llm")
def test_judge_alignment_handles_call_failure(mock_llm):
    mock_llm.return_value = None
    out = learn_eval.judge_alignment(
        candidate={"changelog": "x"}, golden={"changelog": "y"},
    )
    assert out["error"] == "judge_call_failed"


# ---------------------------------------------------------------------------
# run_eval orchestration
# ---------------------------------------------------------------------------


@patch("backend.eval.learn_eval.call_llm")
@patch("backend.eval.learn_eval.call_llm_with_usage")
def test_run_eval_persists_summary(
    mock_call, mock_judge, fake_table, sample_profile,
):
    """End-to-end: candidate + golden + alignment judge → DDB has META."""
    mock_call.return_value = (_ok_learn_text(), {"tokens_in": 500, "tokens_out": 200})
    mock_judge.return_value = _alignment_response(overall=4)

    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, "", area)
    db.put_profile_hypothesis(
        fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["hypothesis"],
    )

    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#p1",
        "paper_id": "p1",
        "paper": {"id": "p1", "title": "T"},
        "engagement": {"read": True},
        "pinned_insights": [],
    })

    summary = learn_eval.run_eval(
        fake_table, model="zai.glm-5", baseline_model="us.anthropic.claude-sonnet-4-6",
    )

    assert summary["candidate_success"] is True
    assert summary["golden_success"] is True
    assert int(summary["overall_alignment"]) == 4
    # Both candidate + golden ran (different models)
    assert mock_call.call_count == 2

    runs = learn_eval.list_runs(fake_table)
    assert len(runs) == 1


@patch("backend.eval.learn_eval.call_llm")
@patch("backend.eval.learn_eval.call_llm_with_usage")
def test_run_eval_skips_double_call_when_baseline_equals_model(
    mock_call, mock_judge, fake_table, sample_profile,
):
    """If model == baseline_model, only one LLM call should fire."""
    mock_call.return_value = (_ok_learn_text(), {"tokens_in": 500, "tokens_out": 200})
    mock_judge.return_value = _alignment_response(overall=5)

    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#p1",
        "paper_id": "p1",
        "paper": {"id": "p1", "title": "T"},
        "engagement": {"read": True},
        "pinned_insights": [],
    })

    learn_eval.run_eval(
        fake_table,
        model="us.anthropic.claude-sonnet-4-6",
        baseline_model="us.anthropic.claude-sonnet-4-6",
    )
    assert mock_call.call_count == 1  # only one LLM call


def test_run_eval_raises_when_profile_missing(fake_table):
    with pytest.raises(RuntimeError, match="no profile"):
        learn_eval.run_eval(fake_table, model="m")

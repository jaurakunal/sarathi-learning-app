"""Tests for backend.eval.triage_eval — runner + metric calculations."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.eval import dataset as eval_dataset
from backend.eval import triage_eval
from backend.shared import db


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def test_parse_triage_json_strips_code_fences():
    raw = "```json\n{\"triage_score\": 0.8, \"worth_my_hours\": true}\n```"
    parsed = triage_eval._parse_triage_json(raw)
    assert parsed["triage_score"] == 0.8
    assert parsed["worth_my_hours"] is True


def test_parse_triage_json_handles_invalid():
    assert triage_eval._parse_triage_json("not json") is None
    assert triage_eval._parse_triage_json("") is None
    assert triage_eval._parse_triage_json(None) is None


# ---------------------------------------------------------------------------
# Metric calculators
# ---------------------------------------------------------------------------


def test_compute_mae():
    assert triage_eval.compute_mae([(0.5, 0.5), (0.8, 1.0)]) == pytest.approx(0.1)
    assert triage_eval.compute_mae([]) == 0.0
    # All exact matches
    assert triage_eval.compute_mae([(0.7, 0.7), (0.3, 0.3)]) == 0.0


def test_compute_pearson_perfect_correlation():
    pairs = [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6), (0.7, 0.8)]
    assert triage_eval.compute_pearson(pairs) == pytest.approx(1.0)


def test_compute_pearson_zero_variance_returns_zero():
    # All candidates the same → no variance → undefined → return 0
    assert triage_eval.compute_pearson([(0.5, 0.5), (0.5, 0.7), (0.5, 0.9)]) == 0.0


def test_compute_pearson_short_input_returns_zero():
    assert triage_eval.compute_pearson([(0.5, 0.5)]) == 0.0
    assert triage_eval.compute_pearson([]) == 0.0


def test_compute_classification_accuracy():
    assert triage_eval.compute_classification_accuracy(
        [(True, True), (False, False), (True, False)]
    ) == pytest.approx(2 / 3, abs=1e-3)
    assert triage_eval.compute_classification_accuracy([]) == 0.0


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_aggregate_triage_results_skips_failures():
    per_paper = [
        {
            "success": True,
            "candidate": {
                "worth_my_hours": True, "triage_score": 0.7,
                "level": "just_right", "hypothesis_relevant": True,
            },
            "golden": {
                "worth_my_hours": True, "triage_score": 0.6,
                "level": "just_right", "hypothesis_relevant": True,
            },
        },
        {
            "success": True,
            "candidate": {
                "worth_my_hours": False, "triage_score": 0.2,
                "level": "too_basic", "hypothesis_relevant": False,
            },
            "golden": {
                "worth_my_hours": True, "triage_score": 0.5,
                "level": "just_right", "hypothesis_relevant": True,
            },
        },
        {"success": False, "error": "llm_generation_failed"},  # ignored
    ]
    agg = triage_eval.aggregate_triage_results(per_paper)
    assert agg["papers_evaluated"] == 2
    # MAE: |0.7-0.6| + |0.2-0.5| = 0.1 + 0.3 = 0.4 / 2 = 0.2
    assert agg["triage_score_mae"] == pytest.approx(0.2)
    # worth_my_hours: 1 of 2 match
    assert agg["worth_my_hours_accuracy"] == pytest.approx(0.5)
    # level: 1 of 2 match
    assert agg["level_accuracy"] == pytest.approx(0.5)


def test_aggregate_handles_no_papers():
    agg = triage_eval.aggregate_triage_results([])
    assert agg["papers_evaluated"] == 0
    assert agg["triage_score_mae"] == 0.0
    assert agg["worth_my_hours_accuracy"] == 0.0


# ---------------------------------------------------------------------------
# run_one_paper
# ---------------------------------------------------------------------------


def _ok_triage_text(triage_score=0.8, worth_my_hours=True, level="just_right",
                    hypothesis_relevant=True) -> str:
    return json.dumps({
        "triage_score": triage_score,
        "worth_my_hours": worth_my_hours,
        "level": level,
        "hypothesis_relevant": hypothesis_relevant,
        "reasoning": "A reason.",
    })


def _entry_with_golden(paper_id="p1"):
    return {
        "paper_id": paper_id,
        "paper": {
            "id": paper_id,
            "title": "Sample paper",
            "abstract": "Abstract here.",
            "authors": ["A"],
            "areas_matched": ["m1"],
            "worth_my_hours": True,
            "triage_score": 0.7,
            "triage_level": "just_right",
            "hypothesis_relevant": True,
            "triage_reasoning": "Golden reason.",
        },
    }


@patch("backend.eval.triage_eval.call_llm_with_usage")
def test_run_one_paper_happy_path(mock_call, sample_profile):
    mock_call.return_value = (
        _ok_triage_text(triage_score=0.6, worth_my_hours=True),
        {"tokens_in": 80, "tokens_out": 50},
    )
    entry = _entry_with_golden()
    result = triage_eval.run_one_paper(
        entry=entry, profile=sample_profile, model="zai.glm-5",
    )
    assert result["success"] is True
    assert result["candidate"]["triage_score"] == 0.6
    assert result["candidate"]["worth_my_hours"] is True
    assert result["golden"]["worth_my_hours"] is True
    assert result["golden"]["triage_score"] == 0.7
    assert result["tokens_in"] == 80
    assert result["cost_usd"] > 0


@patch("backend.eval.triage_eval.call_llm_with_usage")
def test_run_one_paper_clamps_score_above_one(mock_call, sample_profile):
    mock_call.return_value = (
        _ok_triage_text(triage_score=1.5),
        {"tokens_in": 50, "tokens_out": 30},
    )
    entry = _entry_with_golden()
    result = triage_eval.run_one_paper(
        entry=entry, profile=sample_profile, model="zai.glm-5",
    )
    assert result["candidate"]["triage_score"] == 1.0


@patch("backend.eval.triage_eval.call_llm_with_usage")
def test_run_one_paper_falls_back_to_just_right_for_invalid_level(mock_call, sample_profile):
    mock_call.return_value = (
        _ok_triage_text(level="bogus"),
        {"tokens_in": 50, "tokens_out": 30},
    )
    entry = _entry_with_golden()
    result = triage_eval.run_one_paper(
        entry=entry, profile=sample_profile, model="zai.glm-5",
    )
    assert result["candidate"]["level"] == "just_right"


@patch("backend.eval.triage_eval.call_llm_with_usage")
def test_run_one_paper_handles_llm_failure(mock_call, sample_profile):
    mock_call.return_value = (None, {})
    entry = _entry_with_golden()
    result = triage_eval.run_one_paper(
        entry=entry, profile=sample_profile, model="zai.glm-5",
    )
    assert result["success"] is False
    assert result["error"] == "llm_generation_failed"


@patch("backend.eval.triage_eval.call_llm_with_usage")
def test_run_one_paper_handles_invalid_json(mock_call, sample_profile):
    mock_call.return_value = ("not json", {"tokens_in": 50, "tokens_out": 30})
    entry = _entry_with_golden()
    result = triage_eval.run_one_paper(
        entry=entry, profile=sample_profile, model="zai.glm-5",
    )
    assert result["success"] is False
    assert result["error"] == "triage_json_parse_failed"


def test_run_one_paper_missing_golden_short_circuits(sample_profile):
    entry = {
        "paper_id": "p1",
        "paper": {
            "id": "p1",
            "title": "T",
            "abstract": "A",
            # No golden triage values
        },
    }
    result = triage_eval.run_one_paper(
        entry=entry, profile=sample_profile, model="any",
    )
    assert result["success"] is False
    assert result["error"] == "missing_golden_triage"


# ---------------------------------------------------------------------------
# run_eval orchestration
# ---------------------------------------------------------------------------


@patch("backend.eval.triage_eval.call_llm_with_usage")
def test_run_eval_persists_results_and_summary(
    mock_call, fake_table, sample_profile,
):
    mock_call.return_value = (
        _ok_triage_text(triage_score=0.65, worth_my_hours=True),
        {"tokens_in": 80, "tokens_out": 40},
    )
    # Seed test user profile
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, area)
    db.put_profile_hypothesis(fake_table, eval_dataset.TEST_USER_ID, sample_profile["hypothesis"])

    # Seed dataset
    paper = _entry_with_golden("paper-A")["paper"]
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": f"PAPER#{paper['id']}",
        "paper_id": paper["id"],
        "paper": paper,
    })

    summary = triage_eval.run_eval(
        fake_table, model="zai.glm-5", max_workers=1,
    )

    assert summary["papers_total"] == 1
    assert summary["papers_succeeded"] == 1
    assert summary["model"] == "zai.glm-5"
    # MAE: |0.65 - 0.7| = 0.05
    assert summary["triage_score_mae"] == pytest.approx(0.05, abs=1e-2)

    runs = triage_eval.list_runs(fake_table)
    assert len(runs) == 1
    assert runs[0]["run_id"] == summary["run_id"]

    paper_records = triage_eval.load_run_papers(fake_table, summary["run_id"])
    assert len(paper_records) == 1
    assert float(paper_records[0]["candidate"]["triage_score"]) == pytest.approx(0.65)


def test_run_eval_raises_when_profile_missing(fake_table):
    with pytest.raises(RuntimeError, match="no profile"):
        triage_eval.run_eval(fake_table, model="m", max_workers=1)


def test_run_eval_raises_when_dataset_missing(fake_table, sample_profile):
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    with pytest.raises(RuntimeError, match="dataset"):
        triage_eval.run_eval(fake_table, model="m", max_workers=1)

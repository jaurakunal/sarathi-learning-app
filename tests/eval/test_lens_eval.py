"""Tests for backend.eval.lens_eval — verdict extraction, judge, run."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.eval import dataset as eval_dataset
from backend.eval import lens_eval
from backend.shared import db


# ---------------------------------------------------------------------------
# extract_verdict
# ---------------------------------------------------------------------------


def test_extract_verdict_supports():
    assert lens_eval.extract_verdict(
        "This paper supports the hypothesis by demonstrating..."
    ) == "supports"


def test_extract_verdict_refutes():
    assert lens_eval.extract_verdict(
        "The findings refute the user's thesis."
    ) == "refutes"


def test_extract_verdict_refines():
    assert lens_eval.extract_verdict(
        "The paper refines the hypothesis with a nuanced view."
    ) == "refines"


def test_extract_verdict_irrelevant():
    assert lens_eval.extract_verdict(
        "This paper is irrelevant to the hypothesis."
    ) == "irrelevant"


def test_extract_verdict_unknown_for_empty_or_unmatched():
    assert lens_eval.extract_verdict("") == "unknown"
    assert lens_eval.extract_verdict(None) == "unknown"
    assert lens_eval.extract_verdict("Just a paper.") == "unknown"


def test_extract_verdict_supports_wins_over_refines_in_priority():
    """First match in priority order wins; supports comes before refines."""
    text = "This paper supports and refines the hypothesis."
    assert lens_eval.extract_verdict(text) == "supports"


# ---------------------------------------------------------------------------
# Reasoning judge
# ---------------------------------------------------------------------------


@patch("backend.eval.lens_eval.call_llm")
def test_judge_reasoning_coherent_yes(mock_llm):
    mock_llm.return_value = "yes"
    out = lens_eval.judge_reasoning_coherent(
        hypothesis="H", paper={"title": "T", "abstract": "A"},
        candidate_text="The paper supports H because of X.",
    )
    assert out is True


@patch("backend.eval.lens_eval.call_llm")
def test_judge_reasoning_coherent_no(mock_llm):
    mock_llm.return_value = "no"
    out = lens_eval.judge_reasoning_coherent(
        hypothesis="H", paper={"title": "T", "abstract": "A"},
        candidate_text="Generic text.",
    )
    assert out is False


@patch("backend.eval.lens_eval.call_llm")
def test_judge_reasoning_coherent_handles_unparseable(mock_llm):
    mock_llm.return_value = "I think... maybe."
    out = lens_eval.judge_reasoning_coherent(
        hypothesis="H", paper={"title": "T", "abstract": "A"},
        candidate_text="x",
    )
    assert out is None


@patch("backend.eval.lens_eval.call_llm")
def test_judge_reasoning_coherent_handles_failure(mock_llm):
    mock_llm.return_value = None
    out = lens_eval.judge_reasoning_coherent(
        hypothesis="H", paper={"title": "T", "abstract": "A"},
        candidate_text="x",
    )
    assert out is None


def test_judge_reasoning_coherent_returns_false_for_empty_text():
    out = lens_eval.judge_reasoning_coherent(
        hypothesis="H", paper={"title": "T", "abstract": "A"},
        candidate_text="",
    )
    assert out is False


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_aggregate_lens_results_combined_alignment():
    per_paper = [
        # match + coherent → counts toward alignment
        {"success": True, "verdict_match": True, "reasoning_coherent": True,
         "candidate_verdict": "supports"},
        # match but incoherent → not aligned
        {"success": True, "verdict_match": True, "reasoning_coherent": False,
         "candidate_verdict": "supports"},
        # mismatch but coherent → not aligned
        {"success": True, "verdict_match": False, "reasoning_coherent": True,
         "candidate_verdict": "refutes"},
        {"success": False, "error": "x"},  # ignored
    ]
    agg = lens_eval.aggregate_lens_results(per_paper)
    assert agg["papers_evaluated"] == 3
    # 2/3 matches
    assert agg["verdict_match_pct"] == pytest.approx(66.7, abs=0.1)
    # 2/3 coherent
    assert agg["reasoning_coherent_pct"] == pytest.approx(66.7, abs=0.1)
    # 1/3 fully aligned
    assert agg["lens_alignment_pct"] == pytest.approx(33.3, abs=0.1)


def test_aggregate_lens_results_handles_empty():
    agg = lens_eval.aggregate_lens_results([])
    assert agg["papers_evaluated"] == 0
    assert agg["verdict_match_pct"] == 0.0
    assert agg["lens_alignment_pct"] == 0.0


def test_aggregate_lens_with_mixed_positive_and_negative():
    """Aggregator should split per-class metrics on relevance."""
    per_paper = [
        # Positive — both say supports → relevant=True
        {"success": True, "is_negative": False, "verdict_match": True,
         "reasoning_coherent": True,
         "candidate_verdict": "supports", "golden_verdict": "supports"},
        # Positive — golden refines, candidate refutes (still relevant=True both)
        {"success": True, "is_negative": False, "verdict_match": False,
         "reasoning_coherent": True,
         "candidate_verdict": "refutes", "golden_verdict": "refines"},
        # Negative — both say irrelevant
        {"success": True, "is_negative": True, "verdict_match": True,
         "reasoning_coherent": True,
         "candidate_verdict": "irrelevant", "golden_verdict": "irrelevant"},
        # Negative — candidate says supports (FP); golden says irrelevant
        {"success": True, "is_negative": True, "verdict_match": False,
         "reasoning_coherent": False,
         "candidate_verdict": "supports", "golden_verdict": "irrelevant"},
    ]
    agg = lens_eval.aggregate_lens_results(per_paper)
    assert agg["positives_evaluated"] == 2
    assert agg["negatives_evaluated"] == 2
    # Both positives are relevant according to both candidate + golden
    assert agg["positives_recall"] == pytest.approx(1.0)
    # Specificity on negatives = 1/2
    assert agg["negatives_specificity"] == pytest.approx(0.5)
    # Confusion matrix on relevance: TP=2, FP=1, TN=1, FN=0
    assert agg["tp"] == 2
    assert agg["fp"] == 1
    assert agg["tn"] == 1
    assert agg["fn"] == 0


def test_is_relevant_verdict_helper():
    assert lens_eval._is_relevant_verdict("supports") is True
    assert lens_eval._is_relevant_verdict("refutes") is True
    assert lens_eval._is_relevant_verdict("refines") is True
    assert lens_eval._is_relevant_verdict("irrelevant") is False
    assert lens_eval._is_relevant_verdict("unknown") is None
    assert lens_eval._is_relevant_verdict(None) is None


# ---------------------------------------------------------------------------
# run_one_paper
# ---------------------------------------------------------------------------


def _entry_with_lens(paper_id="p1", golden_text="The paper supports the hypothesis."):
    return {
        "paper_id": paper_id,
        "paper": {
            "id": paper_id,
            "title": "Sample",
            "abstract": "Abstract.",
        },
        "golden_card": {
            "card_id": "20260615T120000Z_aaa",
            "paper_id": paper_id,
            "hook": "h",
            "digest": {"gist": "g", "key_ideas": ["k"]},
            "hypothesis_relevance": golden_text,
        },
    }


@patch("backend.eval.lens_eval.call_llm")
@patch("backend.eval.lens_eval.call_llm_with_usage")
def test_run_one_paper_happy_path_match(mock_call, mock_judge):
    mock_call.return_value = (
        "This paper supports the hypothesis through architectural choices.",
        {"tokens_in": 60, "tokens_out": 30},
    )
    mock_judge.return_value = "yes"

    result = lens_eval.run_one_paper(
        entry=_entry_with_lens(),
        hypothesis_statement="Architecture > size",
        model="zai.glm-5",
    )
    assert result["success"] is True
    assert result["candidate_verdict"] == "supports"
    assert result["golden_verdict"] == "supports"
    assert result["verdict_match"] is True
    assert result["reasoning_coherent"] is True
    assert result["cost_usd"] > 0


@patch("backend.eval.lens_eval.call_llm")
@patch("backend.eval.lens_eval.call_llm_with_usage")
def test_run_one_paper_verdict_mismatch(mock_call, mock_judge):
    mock_call.return_value = (
        "This paper refutes the hypothesis.",
        {"tokens_in": 40, "tokens_out": 20},
    )
    mock_judge.return_value = "yes"

    result = lens_eval.run_one_paper(
        entry=_entry_with_lens(golden_text="The paper supports the hypothesis."),
        hypothesis_statement="Architecture > size",
        model="zai.glm-5",
    )
    assert result["candidate_verdict"] == "refutes"
    assert result["verdict_match"] is False
    assert result["reasoning_coherent"] is True


@patch("backend.eval.lens_eval.call_llm_with_usage")
def test_run_one_paper_skip_judge_short_circuits(mock_call):
    mock_call.return_value = (
        "This paper supports the hypothesis.",
        {"tokens_in": 40, "tokens_out": 20},
    )
    result = lens_eval.run_one_paper(
        entry=_entry_with_lens(),
        hypothesis_statement="Architecture > size",
        model="zai.glm-5",
        skip_reasoning_judge=True,
    )
    assert result["success"] is True
    assert result["reasoning_coherent"] is None  # not judged


@patch("backend.eval.lens_eval.call_llm_with_usage")
def test_run_one_paper_handles_llm_failure(mock_call):
    mock_call.return_value = (None, {})
    result = lens_eval.run_one_paper(
        entry=_entry_with_lens(),
        hypothesis_statement="H",
        model="zai.glm-5",
        skip_reasoning_judge=True,
    )
    assert result["success"] is False
    assert result["error"] == "llm_generation_failed"


def test_run_one_paper_missing_golden_card_short_circuits():
    entry = {
        "paper_id": "p1",
        "paper": {"id": "p1", "title": "T", "abstract": "A"},
        "golden_card": None,
    }
    result = lens_eval.run_one_paper(
        entry=entry, hypothesis_statement="H", model="any",
        skip_reasoning_judge=True,
    )
    assert result["success"] is False
    assert result["error"] == "missing_golden_card"


@patch("backend.eval.lens_eval.call_llm_with_usage")
def test_run_one_paper_negative_uses_synth_card(mock_call):
    """For negative entries with no golden_card, lens synthesizes one from the
    paper's title + abstract and treats hypothesis_relevant=False as
    'irrelevant' golden verdict."""
    mock_call.return_value = (
        "This paper is irrelevant to the hypothesis.",
        {"tokens_in": 40, "tokens_out": 20},
    )
    entry = {
        "paper_id": "neg-1",
        "paper": {
            "id": "neg-1",
            "title": "Off-topic title",
            "abstract": "Off-topic abstract.",
            "hypothesis_relevant": False,
            "triage_reasoning": "Off-topic.",
        },
        "golden_card": None,
        "is_negative": True,
    }
    result = lens_eval.run_one_paper(
        entry=entry, hypothesis_statement="H", model="zai.glm-5",
        skip_reasoning_judge=True,
    )
    assert result["success"] is True
    assert result["is_negative"] is True
    assert result["golden_verdict"] == "irrelevant"
    assert result["candidate_verdict"] == "irrelevant"
    assert result["verdict_match"] is True


def test_synth_card_from_paper_shape():
    """Helper produces dict with hook + digest fields lens prompt expects."""
    card = lens_eval._synth_card_from_paper({
        "title": "T", "abstract": "A long abstract." * 200,
    })
    assert card["hook"] == "T"
    assert "gist" in card["digest"]
    assert card["digest"]["key_ideas"] == []
    # Truncates very long abstracts
    assert len(card["digest"]["gist"]) <= 1500


# ---------------------------------------------------------------------------
# run_eval orchestration
# ---------------------------------------------------------------------------


@patch("backend.eval.lens_eval.call_llm")
@patch("backend.eval.lens_eval.call_llm_with_usage")
def test_run_eval_persists_summary(
    mock_call, mock_judge, fake_table, sample_profile,
):
    mock_call.return_value = (
        "The paper supports the hypothesis.",
        {"tokens_in": 60, "tokens_out": 30},
    )
    mock_judge.return_value = "yes"

    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, "", area)
    db.put_profile_hypothesis(
        fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["hypothesis"],
    )

    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#paper-1",
        "paper_id": "paper-1",
        "paper": {"id": "paper-1", "title": "T", "abstract": "A"},
        "golden_card": {
            "card_id": "20260615T120000Z_a",
            "paper_id": "paper-1",
            "hook": "h",
            "digest": {"gist": "g", "key_ideas": []},
            "hypothesis_relevance": "The paper supports the hypothesis.",
        },
    })

    summary = lens_eval.run_eval(
        fake_table, model="zai.glm-5", max_workers=1,
    )

    assert summary["papers_total"] == 1
    assert summary["papers_succeeded"] == 1
    assert float(summary["verdict_match_pct"]) == 100.0
    assert float(summary["reasoning_coherent_pct"]) == 100.0
    assert float(summary["lens_alignment_pct"]) == 100.0

    runs = lens_eval.list_runs(fake_table)
    assert len(runs) == 1


def test_run_eval_raises_when_profile_missing(fake_table):
    with pytest.raises(RuntimeError, match="no profile"):
        lens_eval.run_eval(fake_table, model="m")


def test_run_eval_raises_when_no_hypothesis(fake_table, sample_profile):
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    # No hypothesis written
    with pytest.raises(RuntimeError, match="hypothesis"):
        lens_eval.run_eval(fake_table, model="m")


def test_run_eval_raises_when_dataset_missing(fake_table, sample_profile):
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    db.put_profile_hypothesis(
        fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["hypothesis"],
    )
    with pytest.raises(RuntimeError, match="dataset"):
        lens_eval.run_eval(fake_table, model="m")


@patch("backend.eval.lens_eval.call_llm")
@patch("backend.eval.lens_eval.call_llm_with_usage")
def test_run_eval_with_mixed_positive_and_negative(
    mock_call, mock_judge, fake_table, sample_profile,
):
    """run_eval pulls combined dataset and reports per-class metrics."""
    mock_judge.return_value = "yes"
    # Candidate always says "supports" — positive verdict matches positive
    # gold but FAILS on the negative (where gold = irrelevant).
    mock_call.return_value = (
        "This paper supports the hypothesis.",
        {"tokens_in": 40, "tokens_out": 20},
    )

    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, "", area)
    db.put_profile_hypothesis(
        fake_table, eval_dataset.TEST_USER_ID, "", sample_profile["hypothesis"],
    )

    # 1 positive
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#pos-1",
        "paper_id": "pos-1",
        "paper": {"id": "pos-1", "title": "T", "abstract": "A"},
        "golden_card": {
            "hook": "h",
            "digest": {"gist": "g", "key_ideas": []},
            "hypothesis_relevance": "The paper supports the hypothesis.",
        },
    })
    # 1 negative — Sonnet rejected, hypothesis_relevant=False
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_NEG_PK,
        "SK": "PAPER#neg-1",
        "paper_id": "neg-1",
        "paper": {
            "id": "neg-1",
            "title": "Off",
            "abstract": "Off.",
            "hypothesis_relevant": False,
            "triage_reasoning": "Off-topic.",
        },
        "golden_card": None,
        "is_negative": True,
    })

    summary = lens_eval.run_eval(fake_table, model="zai.glm-5", max_workers=1)
    assert summary["positives_total"] == 1
    assert summary["negatives_total"] == 1
    assert summary["positives_evaluated"] == 1
    assert summary["negatives_evaluated"] == 1
    # Positive: candidate=supports, golden=supports → relevant=True both → TP
    # Negative: candidate=supports, golden=irrelevant → FP
    assert summary["tp"] == 1
    assert summary["fp"] == 1
    assert summary["tn"] == 0
    # Positive recall = 1.0; specificity = 0.0 (we kept the FP)
    assert float(summary["positives_recall"]) == pytest.approx(1.0)
    assert float(summary["negatives_specificity"]) == pytest.approx(0.0)

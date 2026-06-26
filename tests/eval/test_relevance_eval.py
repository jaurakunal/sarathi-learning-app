"""Tests for backend.eval.relevance_eval — batch run + classification metrics."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.eval import dataset as eval_dataset
from backend.eval import relevance_eval
from backend.shared import db
from backend.shared.models import Area


# ---------------------------------------------------------------------------
# Index parsing
# ---------------------------------------------------------------------------


def test_parse_indices_plain_json():
    assert relevance_eval._parse_indices("[0, 2, 5]", n_papers=10) == [0, 2, 5]


def test_parse_indices_with_code_fences():
    raw = "```json\n[1, 3]\n```"
    assert relevance_eval._parse_indices(raw, n_papers=10) == [1, 3]


def test_parse_indices_drops_out_of_range():
    assert relevance_eval._parse_indices("[0, 100, 2]", n_papers=5) == [0, 2]


def test_parse_indices_drops_non_int():
    assert relevance_eval._parse_indices('[0, "x", 2]', n_papers=5) == [0, 2]


def test_parse_indices_handles_invalid():
    assert relevance_eval._parse_indices("not json", n_papers=5) is None
    assert relevance_eval._parse_indices('{"foo": 1}', n_papers=5) is None
    assert relevance_eval._parse_indices("", n_papers=5) is None


# ---------------------------------------------------------------------------
# Profile → Area coercion
# ---------------------------------------------------------------------------


def test_profile_to_areas_basic(sample_profile):
    areas = relevance_eval._profile_to_areas(sample_profile)
    assert len(areas) == 1
    assert isinstance(areas[0], Area)
    assert areas[0].label == "Memory Architecture"
    assert "episodic memory" in areas[0].just_right


def test_profile_to_areas_skips_areas_without_id():
    profile = {"areas": [{"label": "noid"}, {"id": "ok", "label": "Ok"}]}
    areas = relevance_eval._profile_to_areas(profile)
    assert len(areas) == 1
    assert areas[0].id == "ok"


def test_profile_to_areas_handles_no_areas():
    assert relevance_eval._profile_to_areas({}) == []


# ---------------------------------------------------------------------------
# compute_classification_metrics
# ---------------------------------------------------------------------------


def test_classification_metrics_perfect_score():
    metrics = relevance_eval.compute_classification_metrics(
        kept=[True, True, False, False],
        golden=[True, True, False, False],
    )
    assert metrics["accuracy"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0
    assert metrics["tp"] == 2
    assert metrics["tn"] == 2


def test_classification_metrics_perfect_recall_low_precision():
    """Filter is too inclusive — kept everything."""
    metrics = relevance_eval.compute_classification_metrics(
        kept=[True, True, True, True],
        golden=[True, True, False, False],
    )
    assert metrics["recall"] == 1.0
    assert metrics["precision"] == 0.5
    assert metrics["accuracy"] == 0.5


def test_classification_metrics_perfect_precision_low_recall():
    """Filter is too strict — only one paper kept."""
    metrics = relevance_eval.compute_classification_metrics(
        kept=[True, False, False, False],
        golden=[True, True, False, False],
    )
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 0.5
    assert metrics["accuracy"] == pytest.approx(0.75)


def test_classification_metrics_handles_empty():
    metrics = relevance_eval.compute_classification_metrics(kept=[], golden=[])
    assert metrics["accuracy"] == 0.0
    assert metrics["f1"] == 0.0


def test_classification_metrics_mismatched_lengths():
    metrics = relevance_eval.compute_classification_metrics(
        kept=[True], golden=[True, False],
    )
    assert metrics["accuracy"] == 0.0


# ---------------------------------------------------------------------------
# run_one_batch
# ---------------------------------------------------------------------------


def _papers_n(n: int) -> list[dict]:
    return [
        {"id": f"p{i}", "title": f"Title {i}", "abstract": f"Abstract {i}"}
        for i in range(n)
    ]


@patch("backend.eval.relevance_eval.call_llm_with_usage")
def test_run_one_batch_keeps_all(mock_call, sample_profile):
    areas = relevance_eval._profile_to_areas(sample_profile)
    papers = _papers_n(5)
    mock_call.return_value = ("[0, 1, 2, 3, 4]", {"tokens_in": 200, "tokens_out": 50})

    out = relevance_eval.run_one_batch(papers=papers, areas=areas, model="zai.glm-5")
    assert out["success"] is True
    assert out["kept_indices"] == [0, 1, 2, 3, 4]
    assert out["cost_usd"] > 0


@patch("backend.eval.relevance_eval.call_llm_with_usage")
def test_run_one_batch_keeps_subset(mock_call, sample_profile):
    areas = relevance_eval._profile_to_areas(sample_profile)
    papers = _papers_n(5)
    mock_call.return_value = ("[1, 3]", {"tokens_in": 200, "tokens_out": 30})

    out = relevance_eval.run_one_batch(papers=papers, areas=areas, model="zai.glm-5")
    assert out["kept_indices"] == [1, 3]


@patch("backend.eval.relevance_eval.call_llm_with_usage")
def test_run_one_batch_handles_llm_failure(mock_call, sample_profile):
    areas = relevance_eval._profile_to_areas(sample_profile)
    papers = _papers_n(5)
    mock_call.return_value = (None, {})

    out = relevance_eval.run_one_batch(papers=papers, areas=areas, model="zai.glm-5")
    assert out["success"] is False
    assert out["error"] == "llm_generation_failed"


@patch("backend.eval.relevance_eval.call_llm_with_usage")
def test_run_one_batch_handles_invalid_response(mock_call, sample_profile):
    areas = relevance_eval._profile_to_areas(sample_profile)
    papers = _papers_n(5)
    mock_call.return_value = ("not json", {"tokens_in": 200, "tokens_out": 30})

    out = relevance_eval.run_one_batch(papers=papers, areas=areas, model="zai.glm-5")
    assert out["success"] is False
    assert out["error"] == "indices_parse_failed"


# ---------------------------------------------------------------------------
# Synthetic off-topic papers sanity
# ---------------------------------------------------------------------------


def test_synthetic_offtopic_papers_well_formed():
    assert len(relevance_eval.SYNTHETIC_OFFTOPIC_PAPERS) >= 10
    for p in relevance_eval.SYNTHETIC_OFFTOPIC_PAPERS:
        assert p.get("id") and p.get("title") and p.get("abstract")
        # Sanity check: titles are NOT about AI/ML/agents
        title_low = p["title"].lower()
        assert not any(t in title_low for t in (
            "language model", "agent", "llm", "neural network",
            "transformer", "attention is all you need",
        ))


# ---------------------------------------------------------------------------
# Near-miss negative selection
# ---------------------------------------------------------------------------


def test_is_near_miss_negative_keyword_match():
    paper = {
        "title": "Some paper",
        "triage_reasoning": "This paper is OFF-TOPIC for the user.",
        "hypothesis_relevant": True,
        "triage_score": 0.6,
    }
    assert relevance_eval._is_near_miss_negative(paper) is True


def test_is_near_miss_negative_low_score_and_irrelevant():
    paper = {
        "triage_reasoning": "Solid paper but unrelated.",  # no keyword
        "hypothesis_relevant": False,
        "triage_score": 0.2,
    }
    # No keyword, but hypothesis_relevant=False AND score<0.4 → near-miss
    assert relevance_eval._is_near_miss_negative(paper) is True


def test_is_near_miss_negative_high_score_excluded():
    """A paper with high triage_score isn't a near-miss negative — Sonnet
    rated it well even if hypothesis_relevant=False."""
    paper = {
        "triage_reasoning": "Useful but tangential.",
        "hypothesis_relevant": False,
        "triage_score": 0.7,
    }
    assert relevance_eval._is_near_miss_negative(paper) is False


def test_select_real_negatives_uses_negative_dataset(fake_table):
    """Negatives marked off-topic in DDB get pulled."""
    # Seed 2 near-miss negatives + 1 too-basic non-near-miss
    for pid, reasoning, score, hyp in [
        ("near-1", "off-topic for the user", 0.5, True),
        ("near-2", "not relevant to the user's areas", 0.3, False),
        ("not-near", "too basic for the user's level", 0.2, True),
    ]:
        fake_table.put_item(Item={
            "PK": eval_dataset.DATASET_NEG_PK,
            "SK": f"PAPER#{pid}",
            "paper_id": pid,
            "is_negative": True,
            "paper": {
                "id": pid,
                "title": f"T{pid}",
                "abstract": "abs",
                "triage_reasoning": reasoning,
                "triage_score": score,
                "hypothesis_relevant": hyp,
            },
        })

    out = relevance_eval._select_real_negatives(fake_table, target=10)
    ids = {p["id"] for p in out}
    # Both near-miss papers selected. The non-near-miss is included as
    # backfill since target=10 and we only have 3 candidates.
    assert "near-1" in ids
    assert "near-2" in ids


def test_select_real_negatives_returns_empty_when_no_negatives(fake_table):
    assert relevance_eval._select_real_negatives(fake_table, target=10) == []


def test_build_eval_paper_set_falls_back_to_synthetic(fake_table):
    """No negative dataset → use SYNTHETIC_OFFTOPIC_PAPERS."""
    # Just one positive
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#pos-1",
        "paper_id": "pos-1",
        "paper": {"id": "pos-1", "title": "Positive", "abstract": "A"},
    })
    papers = relevance_eval._build_eval_paper_set(fake_table)
    pos = [p for p in papers if p["_golden_keep"]]
    neg = [p for p in papers if not p["_golden_keep"]]
    assert len(pos) == 1
    # Falls back to synthetic list
    assert len(neg) == len(relevance_eval.SYNTHETIC_OFFTOPIC_PAPERS)


def test_build_eval_paper_set_uses_real_negatives_when_available(fake_table):
    """When EVAL#DATASET_NEG has near-miss papers, those replace synthetics."""
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#pos-1",
        "paper_id": "pos-1",
        "paper": {"id": "pos-1", "title": "Positive", "abstract": "A"},
    })
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_NEG_PK,
        "SK": "PAPER#near-1",
        "paper_id": "near-1",
        "is_negative": True,
        "paper": {
            "id": "near-1", "title": "Near miss", "abstract": "Adjacent CS.",
            "triage_reasoning": "off-topic for the user",
            "hypothesis_relevant": False, "triage_score": 0.3,
        },
    })
    papers = relevance_eval._build_eval_paper_set(fake_table)
    neg = [p for p in papers if not p["_golden_keep"]]
    neg_ids = {p["id"] for p in neg}
    assert neg_ids == {"near-1"}  # synthetic NOT used


def test_build_eval_paper_set_can_force_synthetic(fake_table):
    """prefer_real_negatives=False ignores DDB negatives."""
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#pos-1",
        "paper_id": "pos-1",
        "paper": {"id": "pos-1", "title": "Positive", "abstract": "A"},
    })
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_NEG_PK,
        "SK": "PAPER#near-1",
        "paper_id": "near-1",
        "is_negative": True,
        "paper": {
            "id": "near-1", "title": "Near miss", "abstract": "A",
            "triage_reasoning": "off-topic", "hypothesis_relevant": False,
            "triage_score": 0.2,
        },
    })
    papers = relevance_eval._build_eval_paper_set(
        fake_table, prefer_real_negatives=False,
    )
    neg = [p for p in papers if not p["_golden_keep"]]
    assert len(neg) == len(relevance_eval.SYNTHETIC_OFFTOPIC_PAPERS)


# ---------------------------------------------------------------------------
# run_eval orchestration
# ---------------------------------------------------------------------------


@patch("backend.eval.relevance_eval.call_llm_with_usage")
def test_run_eval_persists_summary(mock_call, fake_table, sample_profile):
    """End-to-end: positive + negative papers, candidate keeps positives only."""
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, area)

    # Seed 2 positive papers in EVAL#DATASET
    for pid in ("paper-A", "paper-B"):
        fake_table.put_item(Item={
            "PK": eval_dataset.DATASET_PK,
            "SK": f"PAPER#{pid}",
            "paper_id": pid,
            "paper": {"id": pid, "title": f"AI {pid}", "abstract": "Memory."},
        })

    # The filter receives positives + 12 synthetic negatives = 14 papers.
    # Mock: keep first 2 (positives) — perfect classification.
    def _side_effect(*args, **kwargs):
        return ("[0, 1]", {"tokens_in": 300, "tokens_out": 50})
    mock_call.side_effect = _side_effect

    summary = relevance_eval.run_eval(
        fake_table, model="zai.glm-5", batch_size=25,
    )

    # 2 positives + 12 negatives = 14 papers, all in 1 batch
    assert summary["positives_total"] == 2
    assert summary["negatives_total"] == len(relevance_eval.SYNTHETIC_OFFTOPIC_PAPERS)
    assert summary["papers_evaluated"] == 14
    # Perfect classification
    assert float(summary["accuracy"]) == 1.0
    assert float(summary["precision"]) == 1.0
    assert float(summary["recall"]) == 1.0

    runs = relevance_eval.list_runs(fake_table)
    assert len(runs) == 1


@patch("backend.eval.relevance_eval.call_llm_with_usage")
def test_run_eval_imperfect_classification(mock_call, fake_table, sample_profile):
    """Filter keeps positives + 1 negative → precision drops."""
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, area)

    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#paper-A",
        "paper_id": "paper-A",
        "paper": {"id": "paper-A", "title": "AI A", "abstract": "Memory."},
    })

    # 1 positive + 12 negatives = 13. Keep [0, 1] — paper 0 is a positive (good),
    # paper 1 is one of the negatives (bad).
    mock_call.return_value = ("[0, 1]", {"tokens_in": 300, "tokens_out": 50})

    summary = relevance_eval.run_eval(
        fake_table, model="zai.glm-5", batch_size=25,
    )
    # 1 TP, 1 FP, 11 TN, 0 FN → precision=0.5, recall=1.0
    assert float(summary["recall"]) == 1.0
    assert float(summary["precision"]) == 0.5


def test_run_eval_raises_when_profile_missing(fake_table):
    with pytest.raises(RuntimeError, match="no profile"):
        relevance_eval.run_eval(fake_table, model="m")


def test_run_eval_raises_when_no_areas(fake_table, sample_profile):
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    # No areas
    with pytest.raises(RuntimeError, match="areas"):
        relevance_eval.run_eval(fake_table, model="m")


def test_run_eval_raises_when_dataset_missing(fake_table, sample_profile):
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, area)
    # Dataset PK still empty
    with pytest.raises(RuntimeError, match="dataset"):
        relevance_eval.run_eval(fake_table, model="m")


@patch("backend.eval.relevance_eval.call_llm_with_usage")
def test_run_eval_with_real_negatives(mock_call, fake_table, sample_profile):
    """run_eval picks up real near-miss negatives and reports the source."""
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, area)

    # 1 positive in the dataset
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#pos-1",
        "paper_id": "pos-1",
        "paper": {"id": "pos-1", "title": "Positive", "abstract": "Memory."},
    })
    # 2 real near-miss negatives
    for pid in ("near-1", "near-2"):
        fake_table.put_item(Item={
            "PK": eval_dataset.DATASET_NEG_PK,
            "SK": f"PAPER#{pid}",
            "paper_id": pid,
            "is_negative": True,
            "paper": {
                "id": pid, "title": f"Near {pid}",
                "abstract": "Adjacent CS subfield.",
                "triage_reasoning": "off-topic for the user's areas",
                "hypothesis_relevant": False,
                "triage_score": 0.25,
            },
        })

    # Mock: keep only paper 0 — perfect (positive in, negatives out)
    mock_call.return_value = ("[0]", {"tokens_in": 200, "tokens_out": 30})

    summary = relevance_eval.run_eval(
        fake_table, model="zai.glm-5", batch_size=25,
    )
    assert summary["positives_total"] == 1
    assert summary["negatives_total"] == 2
    assert summary["negatives_source"] == "real"
    # 1 TP, 0 FP, 2 TN, 0 FN → accuracy=1.0
    assert float(summary["accuracy"]) == 1.0
    assert float(summary["precision"]) == 1.0
    assert float(summary["recall"]) == 1.0


@patch("backend.eval.relevance_eval.call_llm_with_usage")
def test_run_eval_records_synthetic_source_when_no_negatives(
    mock_call, fake_table, sample_profile,
):
    db.put_profile_meta(fake_table, eval_dataset.TEST_USER_ID, sample_profile["meta"])
    for area in sample_profile["areas"]:
        db.put_profile_area(fake_table, eval_dataset.TEST_USER_ID, area)
    fake_table.put_item(Item={
        "PK": eval_dataset.DATASET_PK,
        "SK": "PAPER#pos-1",
        "paper_id": "pos-1",
        "paper": {"id": "pos-1", "title": "Positive", "abstract": "A."},
    })
    mock_call.return_value = ("[0]", {"tokens_in": 200, "tokens_out": 30})

    summary = relevance_eval.run_eval(
        fake_table, model="zai.glm-5", batch_size=25,
    )
    assert summary["negatives_source"] == "synthetic"
    assert summary["negatives_total"] == len(relevance_eval.SYNTHETIC_OFFTOPIC_PAPERS)

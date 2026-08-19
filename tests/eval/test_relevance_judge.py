"""Tests for the Tier 3 independent relevance judge."""

from __future__ import annotations

from unittest.mock import patch

PROFILE = {
    "areas": [{"label": "RAG", "role": "primary", "current_level": "beginner", "intent": "consume"}],
    "hypothesis": {"statement": "H"},
    "user_meta": {"learning_style": "applied", "math_comfort": "low"},
}
PAPER = {"title": "A RAG survey", "abstract": "We survey retrieval-augmented generation."}


@patch("backend.eval.relevance_judge.call_llm")
def test_judge_parses_relevance(mock_llm):
    from backend.eval.relevance_judge import judge_paper_relevance
    mock_llm.return_value = '{"relevance": 0.82, "on_topic": true, "reason": "on-target survey"}'
    r = judge_paper_relevance(PAPER, PROFILE)
    assert r["relevance"] == 0.82
    assert r["on_topic"] is True
    assert "survey" in r["reason"]


@patch("backend.eval.relevance_judge.call_llm")
def test_judge_clamps_relevance(mock_llm):
    from backend.eval.relevance_judge import judge_paper_relevance
    mock_llm.return_value = '{"relevance": 1.7, "on_topic": true}'
    assert judge_paper_relevance(PAPER, PROFILE)["relevance"] == 1.0
    mock_llm.return_value = '{"relevance": -0.3, "on_topic": false}'
    assert judge_paper_relevance(PAPER, PROFILE)["relevance"] == 0.0


@patch("backend.eval.relevance_judge.call_llm")
def test_judge_none_on_llm_failure(mock_llm):
    from backend.eval.relevance_judge import judge_paper_relevance
    mock_llm.return_value = None
    assert judge_paper_relevance(PAPER, PROFILE)["relevance"] is None


@patch("backend.eval.relevance_judge.call_llm")
def test_judge_none_on_bad_json(mock_llm):
    from backend.eval.relevance_judge import judge_paper_relevance
    mock_llm.return_value = "not json at all"
    assert judge_paper_relevance(PAPER, PROFILE)["relevance"] is None


@patch("backend.eval.relevance_judge.call_llm")
def test_judge_is_blind_to_triage_and_engagement(mock_llm):
    """The prompt must not carry triage_score or engagement into the judge."""
    from backend.eval.relevance_judge import judge_paper_relevance
    mock_llm.return_value = '{"relevance": 0.5, "on_topic": true}'
    paper = {**PAPER, "triage_score": 0.99, "status": "digested"}
    judge_paper_relevance(paper, PROFILE)
    sent = mock_llm.call_args.kwargs["user_message"] + mock_llm.call_args.kwargs["system"]
    assert "0.99" not in sent
    assert "triage" not in sent.lower()
    assert "digested" not in sent.lower()


@patch("backend.eval.relevance_judge.call_llm")
def test_judge_uses_independent_model_default(mock_llm):
    from backend.eval.relevance_judge import judge_paper_relevance, RELEVANCE_JUDGE_MODEL
    mock_llm.return_value = '{"relevance": 0.5}'
    judge_paper_relevance(PAPER, PROFILE)
    model = mock_llm.call_args.kwargs["model_id"]
    assert model == RELEVANCE_JUDGE_MODEL
    # must not be triage's primary
    assert "kimi" not in model.lower() and "moonshot" not in model.lower()

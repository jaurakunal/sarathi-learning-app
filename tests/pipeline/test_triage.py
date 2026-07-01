"""Tests for backend.pipeline.triage — the Triage pipeline step."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Happy path: LLM returns valid JSON, papers get scored and updated
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_happy_path_papers_scored(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_papers, sample_profile):
    """LLM returns valid JSON — papers get triage_score and status updated."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = sample_papers[:2]

    # call_llm returns a JSON string directly
    mock_call_llm.return_value = json.dumps({
        "triage_score": 0.85,
        "level": "just_right",
        "hypothesis_relevant": True,
        "reasoning": "Directly applicable to memory architecture work.",
        "worth_my_hours": True,
    })

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["papers_triaged"] == 2
    assert result["worth_reading"] == 2
    assert mock_db.put_paper.call_count == 2

    # Verify the paper was updated with triage results
    first_call_paper = mock_db.put_paper.call_args_list[0][0][3]
    assert first_call_paper["triage_score"] == 0.85
    assert first_call_paper["status"] == "surfaced"
    assert first_call_paper["worth_my_hours"] is True


# ---------------------------------------------------------------------------
# LLM returns malformed JSON → paper gets score=0, pipeline continues
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_malformed_json_scores_zero(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_papers, sample_profile):
    """LLM returns unparseable text — paper gets score=0 and pipeline continues."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_papers[0]]

    # LLM returns invalid JSON
    mock_call_llm.return_value = "This is not JSON at all {{{broken"

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    # Pipeline continues — paper is triaged (with score=0)
    assert result["papers_triaged"] == 1
    assert result["worth_reading"] == 0

    # Paper was still written to DDB (with score=0)
    mock_db.put_paper.assert_called_once()
    written_paper = mock_db.put_paper.call_args[0][3]
    assert written_paper["triage_score"] == 0.0
    assert written_paper["worth_my_hours"] is False


# ---------------------------------------------------------------------------
# LLM API throws → paper gets score=0, pipeline continues
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_api_error_paper_scored_zero(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_papers, sample_profile):
    """LLM API error (returns None) — paper gets score=0, pipeline continues to next paper."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = sample_papers[:2]

    # First call returns None (API failure), second succeeds
    mock_call_llm.side_effect = [
        None,
        json.dumps({
            "triage_score": 0.7,
            "level": "just_right",
            "hypothesis_relevant": False,
            "reasoning": "Decent paper.",
            "worth_my_hours": True,
        }),
    ]

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    # Both papers are triaged (first with score=0, second normally)
    assert result["papers_triaged"] == 2
    assert result["worth_reading"] == 1
    assert mock_db.put_paper.call_count == 2


# ---------------------------------------------------------------------------
# Papers with worth_my_hours=True get status promoted to "surfaced"
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_worth_reading_promoted_to_surfaced(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_papers, sample_profile):
    """Papers deemed worth_my_hours get their status changed to 'surfaced'."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = sample_papers[:2]

    # First paper: worth it, second: not worth it
    mock_call_llm.side_effect = [
        json.dumps({
            "triage_score": 0.9,
            "level": "just_right",
            "hypothesis_relevant": True,
            "reasoning": "Worth it",
            "worth_my_hours": True,
        }),
        json.dumps({
            "triage_score": 0.2,
            "level": "just_right",
            "hypothesis_relevant": False,
            "reasoning": "Not relevant",
            "worth_my_hours": False,
        }),
    ]

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["papers_triaged"] == 2
    assert result["worth_reading"] == 1

    # Check status of both written papers
    first_paper = mock_db.put_paper.call_args_list[0][0][3]
    second_paper = mock_db.put_paper.call_args_list[1][0][3]

    assert first_paper["status"] == "surfaced"
    assert second_paper["status"] == "candidate"  # Not promoted


# ---------------------------------------------------------------------------
# No candidate papers → returns {papers_triaged: 0}
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_no_candidates_returns_zero(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_profile):
    """When there are no candidate papers, returns zero counts."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = []

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["papers_triaged"] == 0
    assert result["worth_reading"] == 0


# ---------------------------------------------------------------------------
# No profile → returns zeros
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_no_profile_returns_zero(mock_db, mock_boto3, mock_call_llm, user_id, table_name):
    """When user has no areas and no hypothesis, handler returns zero."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = {"meta": None, "areas": [], "hypothesis": None, "summaries": []}

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["papers_triaged"] == 0
    assert result["worth_reading"] == 0


# ---------------------------------------------------------------------------
# Verify correct arguments passed to db functions
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_db_calls_correct_arguments(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_papers, sample_profile):
    """Verify db.list_papers_by_status and db.put_paper receive correct args."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_papers[0]]

    mock_call_llm.return_value = json.dumps({
        "triage_score": 0.5,
        "level": "just_right",
        "hypothesis_relevant": False,
        "reasoning": "Meh.",
        "worth_my_hours": False,
    })

    handler({"user_id": user_id, "table_name": table_name}, None)

    # Verify get_full_profile
    mock_db.get_full_profile.assert_called_with(mock_table, user_id, "")

    # Verify list_papers_by_status
    mock_db.list_papers_by_status.assert_called_once_with(mock_table, user_id, "", "candidate", limit=100)

    # Verify put_paper receives table, user_id, workspace_id, paper dict
    mock_db.put_paper.assert_called_once()
    args = mock_db.put_paper.call_args[0]
    assert args[0] is mock_table
    assert args[1] == user_id
    assert "triage_score" in args[3]
    assert "triage_reasoning" in args[3]


# ---------------------------------------------------------------------------
# LLM response with markdown fences is handled gracefully
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_markdown_fenced_json_parsed(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_papers, sample_profile):
    """LLM wraps JSON in ```json fences — still parsed correctly."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_papers[0]]

    # LLM wraps in markdown fences
    json_body = json.dumps({
        "triage_score": 0.75,
        "level": "just_right",
        "hypothesis_relevant": True,
        "reasoning": "Good paper, relevant to harness design.",
        "worth_my_hours": True,
    })
    mock_call_llm.return_value = f"```json\n{json_body}\n```"

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["papers_triaged"] == 1
    assert result["worth_reading"] == 1

    written_paper = mock_db.put_paper.call_args[0][3]
    assert written_paper["triage_score"] == 0.75


# ---------------------------------------------------------------------------
# Triage score is clamped to [0, 1]
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_score_clamped_to_valid_range(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_papers, sample_profile):
    """Triage score > 1 is clamped to 1.0, score < 0 is clamped to 0.0."""
    from backend.pipeline.triage import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_papers[0]]

    # LLM returns score > 1
    mock_call_llm.return_value = json.dumps({
        "triage_score": 1.5,
        "level": "just_right",
        "hypothesis_relevant": True,
        "reasoning": "Amazing paper.",
        "worth_my_hours": True,
    })

    handler({"user_id": user_id, "table_name": table_name}, None)

    written_paper = mock_db.put_paper.call_args[0][3]
    assert written_paper["triage_score"] == 1.0


# ---------------------------------------------------------------------------
# Triage uses call_llm_with_fallback with Kimi primary + Sonnet fallback
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_uses_fallback_wrapper_with_kimi_primary(
    mock_db, mock_boto3, mock_fallback,
    user_id, table_name, sample_papers, sample_profile,
):
    """_score_paper goes through call_llm_with_fallback with Kimi + Sonnet fallback."""
    from backend.pipeline.triage import handler, FALLBACK_MODEL

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_papers[0]]

    mock_fallback.return_value = json.dumps({
        "triage_score": 0.5,
        "level": "just_right",
        "hypothesis_relevant": False,
        "reasoning": "Meh.",
        "worth_my_hours": False,
    })

    handler({
        "user_id": user_id,
        "table_name": table_name,
        "model": "moonshotai.kimi-k2.5",
    }, None)

    mock_fallback.assert_called_once()
    kwargs = mock_fallback.call_args.kwargs
    assert kwargs["primary_model"] == "moonshotai.kimi-k2.5"
    assert kwargs["fallback_model"] == FALLBACK_MODEL
    assert FALLBACK_MODEL == "us.anthropic.claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Triage handler defaults to TRIAGE_MODEL env (Kimi K2.5) when 'model' missing
# ---------------------------------------------------------------------------

@patch("backend.pipeline.triage.call_llm_with_fallback")
@patch("backend.pipeline.triage.boto3")
@patch("backend.pipeline.triage.db")
def test_default_model_when_event_omits_it(
    mock_db, mock_boto3, mock_fallback,
    user_id, table_name, sample_papers, sample_profile,
):
    """When event has no 'model' key, falls back to module DEFAULT_MODEL (env-driven)."""
    from backend.pipeline.triage import handler, DEFAULT_MODEL

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_papers[0]]

    mock_fallback.return_value = json.dumps({
        "triage_score": 0.5,
        "level": "just_right",
        "hypothesis_relevant": False,
        "reasoning": "Meh.",
        "worth_my_hours": False,
    })

    handler({"user_id": user_id, "table_name": table_name}, None)

    kwargs = mock_fallback.call_args.kwargs
    assert kwargs["primary_model"] == DEFAULT_MODEL

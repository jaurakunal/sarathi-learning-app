"""Tests for the Suggest API handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.api.suggest import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(method="POST", body=None, user_id="test-user-123"):
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
        "body": json.dumps(body) if body else None,
    }


# ---------------------------------------------------------------------------
# POST /suggest
# ---------------------------------------------------------------------------


class TestPostSuggest:
    @patch("backend.api.suggest.call_llm")
    @patch("backend.api.suggest.boto3")
    @patch("backend.api.suggest.db")
    def test_returns_3_suggestions(self, mock_db, mock_boto3, mock_call_llm):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        mock_db.get_conversation_turns.return_value = [
            {"request": "What is RLHF?", "response": "RLHF stands for..."},
            {"request": "How does it work?", "response": "It works by..."},
        ]
        mock_db.get_full_profile.return_value = {
            "areas": [{"label": "AI alignment"}, {"label": "Person cloning"}],
            "hypothesis": {"statement": "Faithful AI requires..."},
            "meta": None,
            "summaries": [],
        }

        suggestions = [
            "How does RLHF relate to alignment?",
            "What are the limitations of this approach?",
            "Can this be applied to person cloning?",
        ]
        mock_call_llm.return_value = json.dumps(suggestions)

        result = handler(_make_event("POST", {"paper_id": "paper-001"}), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "suggestions" in body
        assert len(body["suggestions"]) == 3
        assert body["suggestions"][0] == "How does RLHF relate to alignment?"

    @patch("backend.api.suggest.call_llm")
    @patch("backend.api.suggest.boto3")
    @patch("backend.api.suggest.db")
    def test_uses_haiku_model(self, mock_db, mock_boto3, mock_call_llm):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_turns.return_value = []
        mock_db.get_full_profile.return_value = {
            "areas": [], "hypothesis": {}, "meta": None, "summaries": []
        }
        mock_call_llm.return_value = '["Q1?", "Q2?", "Q3?"]'

        handler(_make_event("POST", {"paper_id": "p1"}), None)

        call_kwargs = mock_call_llm.call_args[1]
        assert "haiku" in call_kwargs["model_id"]

    @patch("backend.api.suggest.call_llm")
    @patch("backend.api.suggest.boto3")
    @patch("backend.api.suggest.db")
    def test_llm_failure_returns_empty_suggestions(self, mock_db, mock_boto3, mock_call_llm):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_turns.return_value = []
        mock_db.get_full_profile.return_value = {
            "areas": [], "hypothesis": {}, "meta": None, "summaries": []
        }
        mock_call_llm.side_effect = Exception("LLM error")

        result = handler(_make_event("POST", {"paper_id": "p1"}), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["suggestions"] == []

    def test_missing_paper_id_returns_400(self):
        result = handler(_make_event("POST", {}), None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "paper_id" in body["error"]

    def test_no_auth_returns_401(self):
        result = handler(_make_event("POST", {"paper_id": "p1"}, user_id=""), None)
        assert result["statusCode"] == 401

    @patch("backend.api.suggest.call_llm")
    @patch("backend.api.suggest.boto3")
    @patch("backend.api.suggest.db")
    def test_truncates_to_3_suggestions(self, mock_db, mock_boto3, mock_call_llm):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_turns.return_value = []
        mock_db.get_full_profile.return_value = {
            "areas": [], "hypothesis": {}, "meta": None, "summaries": []
        }
        # LLM returns 5 suggestions
        mock_call_llm.return_value = '["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]'

        result = handler(_make_event("POST", {"paper_id": "p1"}), None)

        body = json.loads(result["body"])
        assert len(body["suggestions"]) == 3

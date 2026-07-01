"""Tests for the Conversations API handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.api.conversations import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(method="GET", body=None, user_id="test-user-123", path_params=None):
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
        "body": json.dumps(body) if body else None,
        "pathParameters": path_params,
    }


# ---------------------------------------------------------------------------
# GET /conversations
# ---------------------------------------------------------------------------


class TestGetConversations:
    @patch("backend.api.conversations.boto3")
    @patch("backend.api.conversations.db")
    def test_returns_list_of_conversations(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        mock_db.list_all_conversations.return_value = [
            {
                "conv_id": "conv-1",
                "scope": "research",
                "title": "AI Safety",
                "last_active": "2026-06-10T00:00:00.000Z",
                "turn_count": 5,
            },
            {
                "conv_id": "paper-123",
                "scope": "paper",
                "paper_id": "paper-123",
                "title": "",
                "last_active": "2026-06-09T00:00:00.000Z",
                "turn_count": 2,
            },
        ]
        mock_db.get_feed_card_by_paper.return_value = {"hook": "A fascinating paper about X"}

        result = handler(_make_event("GET"), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "conversations" in body
        assert len(body["conversations"]) == 2
        assert body["conversations"][0]["conv_id"] == "conv-1"
        assert body["conversations"][0]["title"] == "AI Safety"

    @patch("backend.api.conversations.boto3")
    @patch("backend.api.conversations.db")
    def test_empty_list(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.list_all_conversations.return_value = []

        result = handler(_make_event("GET"), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["conversations"] == []


# ---------------------------------------------------------------------------
# POST /conversations
# ---------------------------------------------------------------------------


class TestPostConversation:
    @patch("backend.api.conversations.uuid")
    @patch("backend.api.conversations.boto3")
    @patch("backend.api.conversations.db")
    def test_creates_research_conversation(self, mock_db, mock_boto3, mock_uuid):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_uuid.uuid4.return_value = MagicMock(__str__=lambda self: "abcd1234-5678")

        mock_db.create_research_conversation.return_value = {
            "conv_id": "abcd1234-567",
            "title": "New thread",
            "scope": "research",
        }

        body = {"title": "New thread"}
        result = handler(_make_event("POST", body), None)

        assert result["statusCode"] == 201
        resp_body = json.loads(result["body"])
        assert resp_body["scope"] == "research"
        assert "conv_id" in resp_body
        mock_db.create_research_conversation.assert_called_once()


# ---------------------------------------------------------------------------
# PUT /conversations
# ---------------------------------------------------------------------------


class TestPutConversation:
    @patch("backend.api.conversations.boto3")
    @patch("backend.api.conversations.db")
    def test_updates_title(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        body = {"title": "Updated Title"}
        result = handler(_make_event("PUT", body, path_params={"conv_id": "conv-1"}), None)

        assert result["statusCode"] == 200
        mock_db.update_conversation_title.assert_called_once_with(
            mock_table, "test-user-123", "ws-test-fixture", "conv-1", "Updated Title"
        )

    @patch("backend.api.conversations.boto3")
    @patch("backend.api.conversations.db")
    def test_missing_conv_id_returns_400(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        body = {"title": "No conv_id"}
        result = handler(_make_event("PUT", body), None)

        assert result["statusCode"] == 400


# ---------------------------------------------------------------------------
# DELETE /conversations
# ---------------------------------------------------------------------------


class TestDeleteConversation:
    @patch("backend.api.conversations.boto3")
    @patch("backend.api.conversations.db")
    def test_deletes_conversation(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        result = handler(_make_event("DELETE", path_params={"conv_id": "conv-1"}), None)

        assert result["statusCode"] == 200
        mock_db.delete_conversation.assert_called_once_with(
            mock_table, "test-user-123", "ws-test-fixture", "conv-1"
        )

    @patch("backend.api.conversations.boto3")
    @patch("backend.api.conversations.db")
    def test_missing_conv_id_returns_400(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        result = handler(_make_event("DELETE", {}), None)

        assert result["statusCode"] == 400


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_no_auth_returns_401(self):
        result = handler(_make_event("GET", user_id=""), None)
        assert result["statusCode"] == 401

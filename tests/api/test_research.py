"""Tests for the Research scaffold API handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.api.research import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(method="GET", user_id="test-user-123"):
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
        "body": None,
    }


# ---------------------------------------------------------------------------
# GET /research
# ---------------------------------------------------------------------------


class TestGetResearch:
    @patch("backend.api.research.boto3")
    def test_returns_tag_groups_and_stats(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        # Feed cards query
        core_card = {
            "card_id": "c1",
            "paper_id": "p1",
            "hook": "Interesting paper",
            "relevance": "core",
            "tags": ["alignment", "safety"],
            "source_url": "https://arxiv.org/abs/123",
        }
        untagged_engaged = {
            "card_id": "c2",
            "paper_id": "p2",
            "hook": "Another paper",
            "bookmarked": True,
            "tags": [],
        }
        mock_table.query.side_effect = [
            # First query: feed cards
            {"Items": [core_card, untagged_engaged]},
            # Second query: GSI1 conversations
            {"Items": []},
        ]

        result = handler(_make_event(), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])

        # Should have tag groups
        assert "tag_groups" in body
        assert "alignment" in body["tag_groups"]
        assert "safety" in body["tag_groups"]

        # Should have untagged engaged
        assert "untagged_engaged" in body
        assert len(body["untagged_engaged"]) == 1
        assert body["untagged_engaged"][0]["paper_id"] == "p2"

        # Stats
        assert body["stats"]["core_papers"] == 1
        assert body["stats"]["total_tags"] == 2
        assert body["stats"]["untagged_engaged"] == 1

    @patch("backend.api.research.boto3")
    def test_returns_pinned_insights(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        mock_table.query.side_effect = [
            # Feed cards
            {"Items": []},
            # GSI1 conversations
            {"Items": [{"conv_id": "conv-1"}]},
            # Turns query for conv-1 (with FilterExpression for pinned)
            {"Items": [
                {"seq": 1, "request": "What is X?", "response": "X is...", "pinned": True, "pin_note": "key insight", "pinned_at": "2026-06-10T00:00:00.000Z"},
            ]},
        ]

        result = handler(_make_event(), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "pinned_insights" in body
        assert body["stats"]["pinned_insights"] == 1

    @patch("backend.api.research.boto3")
    def test_empty_feed_returns_empty_structure(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        mock_table.query.side_effect = [
            {"Items": []},  # No feed cards
            {"Items": []},  # No conversations
        ]

        result = handler(_make_event(), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["tag_groups"] == {}
        assert body["untagged_engaged"] == []
        assert body["pinned_insights"] == {}
        assert body["stats"]["core_papers"] == 0

    def test_no_auth_returns_401(self):
        result = handler(_make_event(user_id=""), None)
        assert result["statusCode"] == 401

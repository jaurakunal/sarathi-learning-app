"""Tests for the Briefs API handler (GET /briefs)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from boto3.dynamodb.conditions import Key

from backend.api.briefs import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(method="GET", user_id="test-user-123", qs=None):
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
        "queryStringParameters": qs,
        "body": None,
    }


def _brief_item(week: str, content: str = "weekly content", created_at: str | None = None):
    return {
        "PK": "USER#test-user-123#WS#ws-test-fixture#BRIEF",
        "SK": f"WEEK#{week}",
        "user_id": "test-user-123",
        "week": week,
        "content": content,
        "created_at": created_at or f"{week}T17:00:00Z",
    }


# ---------------------------------------------------------------------------
# GET /briefs
# ---------------------------------------------------------------------------


class TestGetBriefs:
    def test_no_auth_returns_401(self):
        result = handler(_make_event(user_id=""), None)
        assert result["statusCode"] == 401

    @patch("backend.api.briefs.boto3")
    def test_returns_empty_list_when_no_briefs(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        result = handler(_make_event(), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body == {"briefs": [], "next_after_week": None}

    @patch("backend.api.briefs.boto3")
    def test_returns_briefs_newest_first(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        # DDB with ScanIndexForward=False already returns newest-first; the handler
        # should preserve that order.
        mock_table.query.return_value = {
            "Items": [
                _brief_item("2026-06-30"),
                _brief_item("2026-06-23"),
                _brief_item("2026-06-16"),
            ],
        }

        result = handler(_make_event(), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        weeks = [b["week"] for b in body["briefs"]]
        assert weeks == ["2026-06-30", "2026-06-23", "2026-06-16"]

        # Verify shape
        first = body["briefs"][0]
        assert set(first.keys()) == {"week", "content", "generated_at"}
        assert first["content"] == "weekly content"
        assert first["generated_at"] == "2026-06-30T17:00:00Z"

    @patch("backend.api.briefs.boto3")
    def test_query_uses_descending_scan(self, mock_boto3):
        """Verify ScanIndexForward=False is passed (newest-first)."""
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        handler(_make_event(), None)

        call_kwargs = mock_table.query.call_args.kwargs
        assert call_kwargs.get("ScanIndexForward") is False

    @patch("backend.api.briefs.boto3")
    def test_filters_to_authenticated_user_pk(self, mock_boto3):
        """Handler must scope its DDB query to the JWT-claim user_id only."""
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        handler(_make_event(user_id="alice-sub"), None)

        # Reconstruct the expected key condition.
        expected = Key("PK").eq("USER#alice-sub#WS#ws-test-fixture#BRIEF")
        actual = mock_table.query.call_args.kwargs["KeyConditionExpression"]
        # The boto3 ConditionBase exposes its components via get_expression().
        assert actual.get_expression() == expected.get_expression()

    @patch("backend.api.briefs.boto3")
    def test_default_limit_is_20(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        handler(_make_event(), None)

        assert mock_table.query.call_args.kwargs.get("Limit") == 20

    @patch("backend.api.briefs.boto3")
    def test_respects_limit_param(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        handler(_make_event(qs={"limit": "5"}), None)

        assert mock_table.query.call_args.kwargs.get("Limit") == 5

    @patch("backend.api.briefs.boto3")
    def test_invalid_limit_falls_back_to_default(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        handler(_make_event(qs={"limit": "not-a-number"}), None)
        assert mock_table.query.call_args.kwargs.get("Limit") == 20

    @patch("backend.api.briefs.boto3")
    def test_limit_capped_at_max(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        handler(_make_event(qs={"limit": "9999"}), None)
        assert mock_table.query.call_args.kwargs.get("Limit") == 100

    @patch("backend.api.briefs.boto3")
    def test_after_week_adds_sk_lt_filter(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        handler(_make_event(qs={"after_week": "2026-06-23"}), None)

        expected = Key("PK").eq("USER#test-user-123#WS#ws-test-fixture#BRIEF") & Key("SK").lt("WEEK#2026-06-23")
        actual = mock_table.query.call_args.kwargs["KeyConditionExpression"]
        assert actual.get_expression() == expected.get_expression()

    @patch("backend.api.briefs.boto3")
    def test_next_after_week_set_when_more_pages(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {
            "Items": [
                _brief_item("2026-06-30"),
                _brief_item("2026-06-23"),
            ],
            "LastEvaluatedKey": {"PK": "x", "SK": "WEEK#2026-06-23"},
        }

        result = handler(_make_event(qs={"limit": "2"}), None)
        body = json.loads(result["body"])
        # Cursor should be the oldest week we returned.
        assert body["next_after_week"] == "2026-06-23"

    @patch("backend.api.briefs.boto3")
    def test_next_after_week_null_when_no_more_pages(self, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.query.return_value = {
            "Items": [_brief_item("2026-06-30")],
            # No LastEvaluatedKey -> we've reached the end.
        }

        result = handler(_make_event(), None)
        body = json.loads(result["body"])
        assert body["next_after_week"] is None

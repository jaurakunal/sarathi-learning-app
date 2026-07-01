"""Tests for the Engagement API handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.api.engagement import handler


def _make_event(body=None, user_sub="test-user-123"):
    """Build a minimal API Gateway event with POST body."""
    return {
        "requestContext": {
            "authorizer": {
                "claims": {"sub": user_sub}
            }
        },
        "body": json.dumps(body) if body else None,
    }


VALID_BODY = {
    "paper_id": "2304.03442",
    "card_id": "20260615_023000_abc123",
    "action": "expand",
    "active_ms": 45000,
    "scroll_depth_pct": 65,
    "interactions": 3,
}


@patch("backend.api.engagement.boto3")
@patch("backend.api.engagement.db")
def test_valid_engagement_returns_201(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    result = handler(_make_event(VALID_BODY), None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["status"] == "ok"
    assert "ts" in body
    mock_db.put_engagement_event.assert_called_once()


@patch("backend.api.engagement.boto3")
@patch("backend.api.engagement.db")
def test_minimal_payload_works(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    body = {"paper_id": "abc", "action": "view"}
    result = handler(_make_event(body), None)

    assert result["statusCode"] == 201


def test_unauthorized_returns_401():
    event = _make_event(VALID_BODY, user_sub="")
    result = handler(event, None)
    assert result["statusCode"] == 401


def test_missing_paper_id_returns_400():
    body = {"action": "expand"}
    result = handler(_make_event(body, user_sub="user1"), None)
    assert result["statusCode"] == 400
    assert "paper_id" in json.loads(result["body"])["error"]


def test_missing_action_returns_400():
    body = {"paper_id": "abc"}
    result = handler(_make_event(body, user_sub="user1"), None)
    assert result["statusCode"] == 400
    assert "action" in json.loads(result["body"])["error"]


def test_invalid_action_returns_400():
    body = {"paper_id": "abc", "action": "invalid_action"}
    result = handler(_make_event(body, user_sub="user1"), None)
    assert result["statusCode"] == 400
    assert "Invalid action" in json.loads(result["body"])["error"]


def test_invalid_json_body_returns_400():
    event = {
        "requestContext": {"authorizer": {"claims": {"sub": "user1"}}},
        "body": "not valid json{{{",
    }
    result = handler(event, None)
    assert result["statusCode"] == 400
    assert "Invalid JSON" in json.loads(result["body"])["error"]


def test_null_body_returns_400():
    event = {
        "requestContext": {"authorizer": {"claims": {"sub": "user1"}}},
        "body": None,
    }
    result = handler(event, None)
    assert result["statusCode"] == 400


@patch("backend.api.engagement.boto3")
@patch("backend.api.engagement.db")
def test_all_valid_actions_accepted(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    for action in ["view", "expand", "read", "dismiss", "bookmark", "ask"]:
        body = {"paper_id": "abc", "action": action}
        result = handler(_make_event(body), None)
        assert result["statusCode"] == 201, f"Action '{action}' should be valid"


@patch("backend.api.engagement.boto3")
@patch("backend.api.engagement.db")
def test_event_written_with_correct_fields(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    handler(_make_event(VALID_BODY), None)

    call_args = mock_db.put_engagement_event.call_args
    event_written = call_args[0][3]  # table, user_id, workspace_id, event
    assert event_written["paper_id"] == "2304.03442"
    assert event_written["card_id"] == "20260615_023000_abc123"
    assert event_written["action"] == "expand"
    assert event_written["active_ms"] == 45000
    assert event_written["scroll_depth_pct"] == 65
    assert event_written["interactions"] == 3
    assert "ts" in event_written


@patch("backend.api.engagement.boto3")
@patch("backend.api.engagement.db")
def test_optional_fields_omitted_when_not_provided(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    body = {"paper_id": "abc", "action": "dismiss"}
    handler(_make_event(body), None)

    call_args = mock_db.put_engagement_event.call_args
    event_written = call_args[0][2]
    assert "active_ms" not in event_written
    assert "scroll_depth_pct" not in event_written
    assert "interactions" not in event_written

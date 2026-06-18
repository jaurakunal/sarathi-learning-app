"""Tests for the Feed API handler."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.api.feed import handler, DecimalEncoder, _strip_internal_keys


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_event(path_params=None, query_params=None, user_sub="test-user-123"):
    """Build a minimal API Gateway event."""
    return {
        "requestContext": {
            "authorizer": {
                "claims": {"sub": user_sub}
            }
        },
        "pathParameters": path_params,
        "queryStringParameters": query_params,
    }


SAMPLE_CARD = {
    "PK": "USER#test-user-123#FEED",
    "SK": "CARD#20260615_023000_abc123",
    "user_id": "test-user-123",
    "gsi1pk": "whatever",
    "card_id": "20260615_023000_abc123",
    "paper_id": "2304.03442",
    "hook": "You built this cold two years ago.",
    "why_you_now": "This is the formal version of your cloning work.",
    "time_estimate": "18 min",
    "card_type": "new_paper",
    "created_at": "2026-06-15T02:30:00Z",
    "source_url": "https://arxiv.org/abs/2304.03442",
    "digest": {
        "gist": "A gist.",
        "key_ideas": ["idea1", "idea2"],
        "deep": "A deep dive.",
    },
    "glossary": [{"term": "reflection", "plain": "when an agent..."}],
    "math_notes": [],
    "hypothesis_relevance": "Supports the bet.",
    "honesty_note": "Landmark paper.",
    "suggested_questions": ["What is reflection?"],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_list_feed_returns_cards(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.list_feed_cards.return_value = ([SAMPLE_CARD], None)
    mock_db.get_read_paper_ids.return_value = set()

    event = _make_event()
    result = handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["cards"]) == 1
    assert body["cards"][0]["card_id"] == "20260615_023000_abc123"
    assert body["cards"][0]["hook"] == "You built this cold two years ago."
    assert body["cards"][0]["read"] is False
    assert body["lastKey"] is None


@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_list_feed_with_pagination(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    next_key = {"PK": "USER#test#FEED", "SK": "CARD#20260614_000000_xyz"}
    mock_db.list_feed_cards.return_value = ([SAMPLE_CARD], next_key)
    mock_db.get_read_paper_ids.return_value = set()

    event = _make_event(query_params={"limit": "5"})
    result = handler(event, None)

    body = json.loads(result["body"])
    assert body["lastKey"] == next_key
    mock_db.list_feed_cards.assert_called_once_with(
        mock_table, "test-user-123", limit=5, last_key=None
    )


@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_list_feed_limit_capped_at_50(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.list_feed_cards.return_value = ([], None)
    mock_db.get_read_paper_ids.return_value = set()

    event = _make_event(query_params={"limit": "999"})
    handler(event, None)

    mock_db.list_feed_cards.assert_called_once_with(
        mock_table, "test-user-123", limit=50, last_key=None
    )


@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_get_single_card(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_feed_card.return_value = SAMPLE_CARD

    event = _make_event(path_params={"card_id": "20260615_023000_abc123"})
    result = handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["card_id"] == "20260615_023000_abc123"
    assert body["digest"]["gist"] == "A gist."
    assert "PK" not in body
    assert "SK" not in body
    assert "user_id" not in body
    assert "gsi1pk" not in body


@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_get_single_card_not_found(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_feed_card.return_value = None

    event = _make_event(path_params={"card_id": "nonexistent"})
    result = handler(event, None)

    assert result["statusCode"] == 404


def test_unauthorized_no_claims():
    event = {"requestContext": {"authorizer": {"claims": {}}}, "pathParameters": None, "queryStringParameters": None}
    result = handler(event, None)
    assert result["statusCode"] == 401


def test_strip_internal_keys():
    cleaned = _strip_internal_keys(SAMPLE_CARD)
    assert "PK" not in cleaned
    assert "SK" not in cleaned
    assert "gsi1pk" not in cleaned
    assert "user_id" not in cleaned
    assert "card_id" in cleaned
    assert "hook" in cleaned


def test_decimal_encoder():
    data = {"score": Decimal("0.95"), "count": Decimal("5")}
    result = json.loads(json.dumps(data, cls=DecimalEncoder))
    assert result["score"] == 0.95
    assert result["count"] == 5


@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_list_feed_empty(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.list_feed_cards.return_value = ([], None)
    mock_db.get_read_paper_ids.return_value = set()

    event = _make_event()
    result = handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["cards"] == []
    assert body["lastKey"] is None


@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_list_feed_marks_read_cards(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.list_feed_cards.return_value = ([SAMPLE_CARD], None)
    mock_db.get_read_paper_ids.return_value = {"2304.03442"}

    event = _make_event()
    result = handler(event, None)

    body = json.loads(result["body"])
    assert body["cards"][0]["read"] is True


@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_cors_headers_present(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.list_feed_cards.return_value = ([], None)
    mock_db.get_read_paper_ids.return_value = set()

    event = _make_event()
    result = handler(event, None)

    assert result["headers"]["Access-Control-Allow-Origin"] == "*"
    assert "Authorization" in result["headers"]["Access-Control-Allow-Headers"]


@patch("backend.api.feed.boto3")
@patch("backend.api.feed.db")
def test_invalid_last_key(mock_db, mock_boto3):
    event = _make_event(query_params={"lastKey": "not-valid-json"})
    result = handler(event, None)

    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert "Invalid lastKey" in body["error"]

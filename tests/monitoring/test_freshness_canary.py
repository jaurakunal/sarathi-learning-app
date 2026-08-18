"""Tests for the feed-freshness canary."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


@patch("backend.monitoring.freshness_canary.metrics")
@patch("backend.monitoring.freshness_canary.db")
@patch("backend.monitoring.freshness_canary.boto3")
def test_breach_when_active_ws_but_no_cards(mock_boto3, mock_db, mock_metrics):
    table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = table
    # one active user, one active workspace
    table.query.return_value = {"Items": [{"PK": "SYSTEM#USERS", "SK": "USER#u1", "user_id": "u1", "status": "active"}]}
    mock_db.list_workspaces.return_value = [{"workspace_id": "w1", "status": "active"}]
    mock_db._feed_pk.return_value = "USER#u1#WS#w1#FEED"

    # The active-users query has no ProjectionExpression; the card query sets
    # ProjectionExpression="created_at". Discriminate on that.
    def query_side_effect(**kwargs):
        if kwargs.get("ProjectionExpression") == "created_at":
            return {"Items": []}  # no cards
        return {"Items": [{"PK": "SYSTEM#USERS", "SK": "USER#u1", "user_id": "u1", "status": "active"}]}
    table.query.side_effect = query_side_effect

    from backend.monitoring.freshness_canary import handler
    result = handler({}, None)

    assert result["active_workspaces"] == 1
    assert result["feed_cards_last_24h"] == 0
    assert result["freshness_breach"] == 1
    mock_metrics.emit.assert_any_call("FeedFreshnessBreach", 1)


@patch("backend.monitoring.freshness_canary.metrics")
@patch("backend.monitoring.freshness_canary.db")
@patch("backend.monitoring.freshness_canary.boto3")
def test_no_breach_when_cards_present(mock_boto3, mock_db, mock_metrics):
    table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = table
    mock_db.list_workspaces.return_value = [{"workspace_id": "w1", "status": "active"}]
    mock_db._feed_pk.return_value = "USER#u1#WS#w1#FEED"

    fresh = "2999-01-01T00:00:00.000Z"  # always >= cutoff
    def query_side_effect(**kwargs):
        if kwargs.get("ProjectionExpression") == "created_at":
            return {"Items": [{"created_at": fresh}, {"created_at": fresh}]}
        return {"Items": [{"user_id": "u1", "status": "active"}]}
    table.query.side_effect = query_side_effect

    from backend.monitoring.freshness_canary import handler
    result = handler({}, None)

    assert result["feed_cards_last_24h"] == 2
    assert result["freshness_breach"] == 0
    mock_metrics.emit.assert_any_call("FeedFreshnessBreach", 0)


@patch("backend.monitoring.freshness_canary.metrics")
@patch("backend.monitoring.freshness_canary.db")
@patch("backend.monitoring.freshness_canary.boto3")
def test_no_breach_when_no_active_workspaces(mock_boto3, mock_db, mock_metrics):
    table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = table
    table.query.return_value = {"Items": []}  # no active users
    mock_db.list_workspaces.return_value = []

    from backend.monitoring.freshness_canary import handler
    result = handler({}, None)

    assert result["active_workspaces"] == 0
    assert result["freshness_breach"] == 0

"""Tests for the weekly product-metrics digest."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


CUR = {
    "day": "2026-08-18",
    "total_users": 12,
    "dau": 4, "wau": 8, "mau": 10,
    "new_signups": 1,
    "funnel": {"signed_up": 12, "user_meta": 9, "completed": 7},
    "engagement": {"reads": 30, "bookmarks": 5, "dismisses": 12, "chat_messages": 18},
    "areas": {"Agents": 4, "Evals": 3, "RAG": 2},
}
PREV = {"day": "2026-08-11", "wau": 5, "mau": 6}


@patch("backend.monitoring.product_digest.db")
def test_description_includes_key_numbers(mock_db):
    from backend.monitoring.product_digest import _build_description
    table = MagicMock()

    def snaps(t, since):
        return [PREV, CUR]
    mock_db.list_metrics_snapshots.side_effect = snaps

    desc = _build_description(table, "2026-08-18")
    assert "12 total" in desc
    assert "DAU 4" in desc and "WAU 8" in desc and "MAU 10" in desc
    assert "(+3)" in desc  # WAU delta 8-5
    assert "12 signed up" in desc and "completed a workspace" in desc
    assert "Agents (4)" in desc


@patch("backend.monitoring.product_digest.db")
def test_description_handles_no_snapshot(mock_db):
    from backend.monitoring.product_digest import _build_description
    mock_db.list_metrics_snapshots.return_value = []
    desc = _build_description(MagicMock(), "2026-08-18")
    assert "No metrics snapshot" in desc


@patch("backend.monitoring.product_digest.boto3")
@patch("backend.monitoring.product_digest.db")
def test_handler_publishes_chatbot_custom_notification(mock_db, mock_boto3):
    from backend.monitoring import product_digest
    product_digest.ALARM_TOPIC_ARN = "arn:aws:sns:us-east-1:123:sarathi-alarms"
    mock_db.list_metrics_snapshots.return_value = [CUR]
    sns = MagicMock()
    mock_boto3.client.return_value = sns
    mock_boto3.resource.return_value.Table.return_value = MagicMock()

    result = product_digest.handler({"day": "2026-08-18"}, None)

    assert result["posted"] is True
    msg = json.loads(sns.publish.call_args[1]["Message"])
    assert msg["source"] == "custom"        # Chatbot custom-notification schema
    assert "content" in msg and "title" in msg["content"]


@patch("backend.monitoring.product_digest.boto3")
@patch("backend.monitoring.product_digest.db")
def test_handler_no_topic_does_not_publish(mock_db, mock_boto3):
    from backend.monitoring import product_digest
    product_digest.ALARM_TOPIC_ARN = ""
    mock_db.list_metrics_snapshots.return_value = [CUR]
    mock_boto3.resource.return_value.Table.return_value = MagicMock()

    result = product_digest.handler({"day": "2026-08-18"}, None)
    assert result["posted"] is False

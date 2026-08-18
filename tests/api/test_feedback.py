"""Tests for POST /feedback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def _event(body, user_id="u1", email="u1@example.com"):
    claims = {"sub": user_id}
    if email:
        claims["email"] = email
    return {
        "httpMethod": "POST",
        "requestContext": {
            "authorizer": {"claims": claims},
            "requestId": "req-123",
            "stage": "prod",
            "identity": {"userAgent": "Mozilla/5.0", "sourceIp": "1.2.3.4"},
        },
        "body": json.dumps(body) if body is not None else None,
    }


@patch("backend.api.feedback.FEEDBACK_TOPIC_ARN", "arn:aws:sns:us-east-1:1:sarathi-feedback")
@patch("backend.api.feedback.resolve_workspace_id", return_value="w1")
@patch("backend.api.feedback.boto3")
def test_valid_feedback_publishes_with_debug_metadata(mock_boto3, mock_resolve):
    mock_sns = MagicMock()
    # boto3.resource for DDB, boto3.client for SNS
    mock_boto3.resource.return_value.Table.return_value = MagicMock()
    mock_boto3.client.return_value = mock_sns

    from backend.api.feedback import handler
    resp = handler(_event({"message": "chat is broken", "category": "bug"}), None)
    assert resp["statusCode"] == 200

    mock_sns.publish.assert_called_once()
    published = json.loads(mock_sns.publish.call_args[1]["Message"])
    assert published["source"] == "custom"
    desc = published["content"]["description"]
    # message + debug metadata present
    assert "chat is broken" in desc
    assert "req-123" in desc          # request_id
    assert "w1" in desc               # workspace_id
    assert "u1@example.com" in desc   # email
    assert "Mozilla/5.0" in desc      # user agent


@patch("backend.api.feedback.boto3")
def test_missing_message_returns_400(mock_boto3):
    mock_boto3.resource.return_value.Table.return_value = MagicMock()
    from backend.api.feedback import handler
    resp = handler(_event({"message": "  "}), None)
    assert resp["statusCode"] == 400


def test_unauthorized_returns_401():
    from backend.api.feedback import handler
    resp = handler({"httpMethod": "POST", "requestContext": {"authorizer": {"claims": {}}}, "body": "{}"}, None)
    assert resp["statusCode"] == 401


@patch("backend.api.feedback.FEEDBACK_TOPIC_ARN", "")
@patch("backend.api.feedback.resolve_workspace_id", return_value="w1")
@patch("backend.api.feedback.boto3")
def test_no_topic_still_200_and_no_publish(mock_boto3, mock_resolve):
    mock_sns = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = MagicMock()
    mock_boto3.client.return_value = mock_sns
    from backend.api.feedback import handler
    resp = handler(_event({"message": "hi", "category": "idea"}), None)
    assert resp["statusCode"] == 200
    mock_sns.publish.assert_not_called()


@patch("backend.api.feedback.FEEDBACK_TOPIC_ARN", "arn:aws:sns:us-east-1:1:t")
@patch("backend.api.feedback.resolve_workspace_id", return_value="w1")
@patch("backend.api.feedback.boto3")
def test_invalid_category_defaults_to_other(mock_boto3, mock_resolve):
    mock_sns = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = MagicMock()
    mock_boto3.client.return_value = mock_sns
    from backend.api.feedback import handler
    resp = handler(_event({"message": "x", "category": "nonsense"}), None)
    assert resp["statusCode"] == 200
    published = json.loads(mock_sns.publish.call_args[1]["Message"])
    assert "OTHER" in published["content"]["description"]

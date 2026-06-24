"""Tests for the Push subscription API handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.api.push import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(method="POST", body=None, user_id="test-user-123"):
    return {
        "httpMethod": method,
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
        "body": json.dumps(body) if body else None,
    }


VALID_SUBSCRIPTION = {
    "subscription": {
        "endpoint": "https://push.example.com/sub/abc123",
        "keys": {"p256dh": "BPk...", "auth": "auth-key"},
    }
}


# ---------------------------------------------------------------------------
# POST /push/subscribe
# ---------------------------------------------------------------------------


class TestPostSubscribe:
    @patch("backend.api.push.boto3")
    @patch("backend.api.push.db")
    def test_valid_subscription_returns_200(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        result = handler(_make_event("POST", VALID_SUBSCRIPTION), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "subscribed"
        mock_db.put_push_subscription.assert_called_once()

    @patch("backend.api.push.boto3")
    @patch("backend.api.push.db")
    def test_missing_endpoint_returns_400(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        body = {"subscription": {"keys": {"p256dh": "k", "auth": "a"}}}
        result = handler(_make_event("POST", body), None)

        assert result["statusCode"] == 400

    @patch("backend.api.push.boto3")
    @patch("backend.api.push.db")
    def test_missing_keys_returns_400(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        body = {"subscription": {"endpoint": "https://push.example.com/x"}}
        result = handler(_make_event("POST", body), None)

        assert result["statusCode"] == 400

    @patch("backend.api.push.boto3")
    @patch("backend.api.push.db")
    def test_missing_subscription_returns_400(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        result = handler(_make_event("POST", {}), None)

        assert result["statusCode"] == 400


# ---------------------------------------------------------------------------
# DELETE /push/subscribe
# ---------------------------------------------------------------------------


class TestDeleteSubscribe:
    @patch("backend.api.push.boto3")
    @patch("backend.api.push.db")
    def test_valid_delete_returns_200(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        body = {"endpoint": "https://push.example.com/sub/abc123"}
        result = handler(_make_event("DELETE", body), None)

        assert result["statusCode"] == 200
        body_resp = json.loads(result["body"])
        assert body_resp["status"] == "unsubscribed"
        mock_db.delete_push_subscription.assert_called_once_with(
            mock_table, "test-user-123", "https://push.example.com/sub/abc123"
        )

    @patch("backend.api.push.boto3")
    @patch("backend.api.push.db")
    def test_missing_endpoint_returns_400(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        result = handler(_make_event("DELETE", {}), None)

        assert result["statusCode"] == 400


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_no_auth_returns_401(self):
        result = handler(_make_event("POST", VALID_SUBSCRIPTION, user_id=""), None)
        assert result["statusCode"] == 401

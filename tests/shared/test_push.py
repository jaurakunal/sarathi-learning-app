"""Unit tests for backend.shared.push — Web Push notification sender."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

from backend.shared import push


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_table():
    return MagicMock()


@pytest.fixture
def vapid_keys():
    return {
        "private_key": "test-private-key-base64",
        "contact_email": "test@example.com",
    }


@pytest.fixture
def sample_subscriptions():
    return [
        {
            "endpoint": "https://push.example.com/sub1",
            "keys": {"p256dh": "key1", "auth": "auth1"},
        },
        {
            "endpoint": "https://push.example.com/sub2",
            "keys": {"p256dh": "key2", "auth": "auth2"},
        },
    ]


# ---------------------------------------------------------------------------
# send_push_notification
# ---------------------------------------------------------------------------


class TestSendPushNotification:
    @patch("pywebpush.webpush")
    @patch("backend.shared.push.db")
    @patch("backend.shared.push._get_vapid_keys")
    def test_sends_to_all_subscriptions(
        self, mock_get_keys, mock_db, mock_webpush, mock_table, vapid_keys, sample_subscriptions
    ):
        mock_get_keys.return_value = vapid_keys
        mock_db.list_push_subscriptions.return_value = sample_subscriptions

        result = push.send_push_notification(
            mock_table, "user-1", "Title", "Body text"
        )

        assert result == 2
        assert mock_webpush.call_count == 2

    @patch("pywebpush.webpush")
    @patch("backend.shared.push.db")
    @patch("backend.shared.push._get_vapid_keys")
    def test_removes_expired_subscription_on_410(
        self, mock_get_keys, mock_db, mock_webpush, mock_table, vapid_keys
    ):
        mock_get_keys.return_value = vapid_keys
        expired_sub = {
            "endpoint": "https://push.example.com/expired",
            "keys": {"p256dh": "k", "auth": "a"},
        }
        mock_db.list_push_subscriptions.return_value = [expired_sub]

        from pywebpush import WebPushException
        mock_webpush.side_effect = WebPushException("410 Gone")

        result = push.send_push_notification(
            mock_table, "user-1", "Title", "Body"
        )

        assert result == 0
        mock_db.delete_push_subscription.assert_called_once_with(
            mock_table, "user-1", "https://push.example.com/expired"
        )

    @patch("backend.shared.push.db")
    @patch("backend.shared.push._get_vapid_keys")
    def test_no_vapid_keys_returns_zero(self, mock_get_keys, mock_db, mock_table):
        mock_get_keys.return_value = None

        result = push.send_push_notification(
            mock_table, "user-1", "Title", "Body"
        )

        assert result == 0
        mock_db.list_push_subscriptions.assert_not_called()

    @patch("backend.shared.push.db")
    @patch("backend.shared.push._get_vapid_keys")
    def test_no_subscriptions_returns_zero(
        self, mock_get_keys, mock_db, mock_table, vapid_keys
    ):
        mock_get_keys.return_value = vapid_keys
        mock_db.list_push_subscriptions.return_value = []

        result = push.send_push_notification(
            mock_table, "user-1", "Title", "Body"
        )

        assert result == 0

    @patch("pywebpush.webpush")
    @patch("backend.shared.push.db")
    @patch("backend.shared.push._get_vapid_keys")
    def test_passes_correct_payload(
        self, mock_get_keys, mock_db, mock_webpush, mock_table, vapid_keys, sample_subscriptions
    ):
        mock_get_keys.return_value = vapid_keys
        mock_db.list_push_subscriptions.return_value = sample_subscriptions[:1]

        push.send_push_notification(
            mock_table, "user-1", "New Paper!", "Check it out", url="/feed"
        )

        call_kwargs = mock_webpush.call_args[1]
        payload = json.loads(call_kwargs["data"])
        assert payload["title"] == "New Paper!"
        assert payload["body"] == "Check it out"
        assert payload["url"] == "/feed"

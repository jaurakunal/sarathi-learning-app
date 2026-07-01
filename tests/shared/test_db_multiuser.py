"""Unit tests for multi-user DB functions in backend.shared.db.

Covers the newer functions added for multi-user support:
- create_research_conversation()
- list_all_conversations()
- delete_conversation()
- pin_turn() / unpin_turn() / get_pinned_turns()
- tag_paper()
- put_push_subscription() / list_push_subscriptions() / delete_push_subscription()

Note: These functions are also covered in test_db.py. This file provides
additional coverage focused on multi-user edge cases and interactions.
"""

import hashlib
from unittest.mock import MagicMock, call, patch

import pytest

from backend.shared import db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_table():
    """A MagicMock that simulates a boto3 DynamoDB Table resource."""
    return MagicMock()


@pytest.fixture
def user_id():
    return "multi-user-test-789"


@pytest.fixture
def other_user_id():
    return "other-user-456"


# ---------------------------------------------------------------------------
# create_research_conversation
# ---------------------------------------------------------------------------


class TestCreateResearchConversation:
    def test_creates_with_all_required_fields(self, mock_table, user_id):
        result = db.create_research_conversation(mock_table, user_id, "", "conv-123", "AI Safety Research")

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#CONV#conv-123"
        assert item["SK"] == "META"
        assert item["user_id"] == user_id
        assert item["conv_id"] == "conv-123"
        assert item["scope"] == "research"
        assert item["title"] == "AI Safety Research"
        assert item["turn_count"] == 0
        assert "created_at" in item
        assert "last_active" in item

    def test_returns_created_item(self, mock_table, user_id):
        result = db.create_research_conversation(mock_table, user_id, "", "conv-x", "Title")

        assert result["conv_id"] == "conv-x"
        assert result["scope"] == "research"
        assert result["title"] == "Title"

    def test_uses_default_title_when_empty(self, mock_table, user_id):
        result = db.create_research_conversation(mock_table, user_id, "", "conv-y", "")

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["title"] == "New conversation"
        assert result["title"] == "New conversation"

    def test_writes_gsi1_attributes(self, mock_table, user_id):
        db.create_research_conversation(mock_table, user_id, "", "conv-z", "Test")

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["gsi1pk"] == f"USER#{user_id}"
        assert item["gsi1sk"] == "CONV#conv-z"

    def test_different_users_get_different_pks(self, mock_table, user_id, other_user_id):
        db.create_research_conversation(mock_table, user_id, "", "shared-conv", "Title")
        item1 = mock_table.put_item.call_args[1]["Item"]

        mock_table.reset_mock()
        db.create_research_conversation(mock_table, other_user_id, "shared-conv", "Title")
        item2 = mock_table.put_item.call_args[1]["Item"]

        assert item1["PK"] != item2["PK"]
        assert item1["gsi1pk"] != item2["gsi1pk"]


# ---------------------------------------------------------------------------
# list_all_conversations
# ---------------------------------------------------------------------------


class TestListAllConversations:
    def test_queries_gsi1_with_user_pk(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        db.list_all_conversations(mock_table, user_id, "")

        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["IndexName"] == "GSI1"
        assert call_kwargs["ScanIndexForward"] is False

    def test_returns_both_paper_and_research_conversations(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"conv_id": "paper-1", "scope": "paper", "paper_id": "p1"},
                {"conv_id": "research-1", "scope": "research", "title": "My Thread"},
                {"conv_id": "paper-2", "scope": "paper", "paper_id": "p2"},
            ]
        }

        result = db.list_all_conversations(mock_table, user_id, "")

        assert len(result) == 3
        scopes = [r["scope"] for r in result]
        assert "paper" in scopes
        assert "research" in scopes

    def test_returns_empty_for_new_user(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.list_all_conversations(mock_table, user_id, "")

        assert result == []


# ---------------------------------------------------------------------------
# delete_conversation
# ---------------------------------------------------------------------------


class TestDeleteConversation:
    def test_deletes_meta_and_all_turns(self, mock_table, user_id):
        pk = f"USER#{user_id}#CONV#conv-del"
        mock_table.query.return_value = {
            "Items": [
                {"PK": pk, "SK": "META"},
                {"PK": pk, "SK": "TURN#00001"},
                {"PK": pk, "SK": "TURN#00002"},
                {"PK": pk, "SK": "TURN#00003"},
            ]
        }
        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        db.delete_conversation(mock_table, user_id, "", "conv-del")

        assert mock_batch_writer.delete_item.call_count == 4

    def test_handles_empty_conversation(self, mock_table, user_id):
        """No items found — batch writer called but no deletes issued."""
        mock_table.query.return_value = {"Items": []}
        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        db.delete_conversation(mock_table, user_id, "", "nonexistent")

        mock_batch_writer.delete_item.assert_not_called()

    def test_queries_correct_pk(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}
        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        db.delete_conversation(mock_table, user_id, "", "conv-x")

        # Verify query uses ProjectionExpression for efficiency
        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["ProjectionExpression"] == "PK, SK"


# ---------------------------------------------------------------------------
# pin_turn / unpin_turn / get_pinned_turns
# ---------------------------------------------------------------------------


class TestPinTurn:
    def test_sets_pinned_true(self, mock_table, user_id):
        db.pin_turn(mock_table, user_id, "", "conv-1", 5)

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#CONV#conv-1",
            "SK": "TURN#00005",
        }
        assert call_kwargs["ExpressionAttributeValues"][":t"] is True

    def test_includes_pinned_at_timestamp(self, mock_table, user_id):
        db.pin_turn(mock_table, user_id, "", "conv-1", 1)

        call_kwargs = mock_table.update_item.call_args[1]
        assert ":ts" in call_kwargs["ExpressionAttributeValues"]
        assert call_kwargs["ExpressionAttributeValues"][":ts"].endswith("Z")

    def test_adds_pin_note_when_provided(self, mock_table, user_id):
        db.pin_turn(mock_table, user_id, "", "conv-1", 2, pin_note="Key finding about memory")

        call_kwargs = mock_table.update_item.call_args[1]
        assert ":note" in call_kwargs["ExpressionAttributeValues"]
        assert call_kwargs["ExpressionAttributeValues"][":note"] == "Key finding about memory"
        assert "pin_note" in call_kwargs["UpdateExpression"]

    def test_no_pin_note_when_empty(self, mock_table, user_id):
        db.pin_turn(mock_table, user_id, "", "conv-1", 3)

        call_kwargs = mock_table.update_item.call_args[1]
        assert ":note" not in call_kwargs["ExpressionAttributeValues"]


class TestUnpinTurn:
    def test_removes_all_pin_attributes(self, mock_table, user_id):
        db.unpin_turn(mock_table, user_id, "", "conv-1", 5)

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#CONV#conv-1",
            "SK": "TURN#00005",
        }
        assert "REMOVE" in call_kwargs["UpdateExpression"]
        assert "pinned" in call_kwargs["UpdateExpression"]
        assert "pinned_at" in call_kwargs["UpdateExpression"]
        assert "pin_note" in call_kwargs["UpdateExpression"]


class TestGetPinnedTurns:
    def test_returns_only_pinned_turns(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"seq": 2, "pinned": True, "request": "Q1", "response": "A1"},
                {"seq": 7, "pinned": True, "request": "Q2", "response": "A2"},
            ]
        }

        result = db.get_pinned_turns(mock_table, user_id, "", "conv-1")

        assert len(result) == 2
        assert all(item["pinned"] is True for item in result)

    def test_returns_empty_when_no_pins(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.get_pinned_turns(mock_table, user_id, "", "conv-1")

        assert result == []

    def test_queries_with_filter_expression(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        db.get_pinned_turns(mock_table, user_id, "", "conv-1")

        call_kwargs = mock_table.query.call_args[1]
        assert "FilterExpression" in call_kwargs


# ---------------------------------------------------------------------------
# tag_paper
# ---------------------------------------------------------------------------


class TestTagPaper:
    def test_sets_relevance_tags_and_timestamp(self, mock_table, user_id):
        db.tag_paper(mock_table, user_id, "", "card-abc", "core", ["alignment", "safety"])

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#FEED",
            "SK": "CARD#card-abc",
        }
        values = call_kwargs["ExpressionAttributeValues"]
        assert values[":r"] == "core"
        assert values[":t"] == ["alignment", "safety"]
        assert values[":ts"].endswith("Z")

    def test_empty_tags_list(self, mock_table, user_id):
        db.tag_paper(mock_table, user_id, "", "card-xyz", "peripheral", [])

        call_kwargs = mock_table.update_item.call_args[1]
        values = call_kwargs["ExpressionAttributeValues"]
        assert values[":r"] == "peripheral"
        assert values[":t"] == []

    def test_update_expression_sets_all_fields(self, mock_table, user_id):
        db.tag_paper(mock_table, user_id, "", "card-1", "core", ["tag1"])

        call_kwargs = mock_table.update_item.call_args[1]
        expr = call_kwargs["UpdateExpression"]
        assert "relevance" in expr
        assert "tags" in expr
        assert "tagged_at" in expr


# ---------------------------------------------------------------------------
# Push Subscriptions
# ---------------------------------------------------------------------------


class TestPutPushSubscription:
    def test_writes_with_hashed_endpoint(self, mock_table, user_id):
        sub = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
            "keys": {"p256dh": "pubkey-data", "auth": "auth-data"},
        }

        db.put_push_subscription(mock_table, user_id, sub)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PUSH"
        assert item["SK"].startswith("SUB#")
        assert len(item["SK"]) == 4 + 16  # "SUB#" + 16-char hash
        assert item["endpoint"] == sub["endpoint"]
        assert item["keys"] == sub["keys"]

    def test_consistent_hashing(self, mock_table, user_id):
        """Same endpoint always produces same SK."""
        sub = {"endpoint": "https://push.example.com/x", "keys": {"p256dh": "k", "auth": "a"}}

        db.put_push_subscription(mock_table, user_id, sub)
        sk1 = mock_table.put_item.call_args[1]["Item"]["SK"]

        mock_table.reset_mock()
        db.put_push_subscription(mock_table, user_id, sub)
        sk2 = mock_table.put_item.call_args[1]["Item"]["SK"]

        assert sk1 == sk2

    def test_different_endpoints_produce_different_sks(self, mock_table, user_id):
        sub1 = {"endpoint": "https://push.example.com/device-1", "keys": {"p256dh": "k", "auth": "a"}}
        sub2 = {"endpoint": "https://push.example.com/device-2", "keys": {"p256dh": "k", "auth": "a"}}

        db.put_push_subscription(mock_table, user_id, sub1)
        sk1 = mock_table.put_item.call_args[1]["Item"]["SK"]

        mock_table.reset_mock()
        db.put_push_subscription(mock_table, user_id, sub2)
        sk2 = mock_table.put_item.call_args[1]["Item"]["SK"]

        assert sk1 != sk2


class TestListPushSubscriptions:
    def test_returns_all_subscriptions(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"endpoint": "https://push.example.com/1", "keys": {"p256dh": "k1", "auth": "a1"}},
                {"endpoint": "https://push.example.com/2", "keys": {"p256dh": "k2", "auth": "a2"}},
                {"endpoint": "https://push.example.com/3", "keys": {"p256dh": "k3", "auth": "a3"}},
            ]
        }

        result = db.list_push_subscriptions(mock_table, user_id)

        assert len(result) == 3

    def test_returns_empty_for_user_with_no_subs(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.list_push_subscriptions(mock_table, user_id)

        assert result == []

    def test_queries_correct_pk_prefix(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        db.list_push_subscriptions(mock_table, user_id)

        mock_table.query.assert_called_once()


class TestDeletePushSubscription:
    def test_deletes_with_correct_key(self, mock_table, user_id):
        endpoint = "https://fcm.googleapis.com/fcm/send/xyz789"

        db.delete_push_subscription(mock_table, user_id, endpoint)

        mock_table.delete_item.assert_called_once()
        key = mock_table.delete_item.call_args[1]["Key"]
        assert key["PK"] == f"USER#{user_id}#PUSH"
        expected_hash = hashlib.sha256(endpoint.encode()).hexdigest()[:16]
        assert key["SK"] == f"SUB#{expected_hash}"

    def test_delete_matches_put_hash(self, mock_table, user_id):
        """The SK used for delete matches what put would have written."""
        endpoint = "https://push.example.com/test-endpoint"
        sub = {"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}}

        db.put_push_subscription(mock_table, user_id, sub)
        put_sk = mock_table.put_item.call_args[1]["Item"]["SK"]

        mock_table.reset_mock()
        db.delete_push_subscription(mock_table, user_id, endpoint)
        delete_sk = mock_table.delete_item.call_args[1]["Key"]["SK"]

        assert put_sk == delete_sk


# ---------------------------------------------------------------------------
# Pipeline Run (deduplication)
# ---------------------------------------------------------------------------


class TestGetPipelineRun:
    def test_returns_item_when_exists(self, mock_table, user_id):
        mock_table.get_item.return_value = {
            "Item": {
                "PK": f"USER#{user_id}#PIPELINE",
                "SK": "LATEST",
                "execution_arn": "arn:exec:123",
                "status": "running",
            }
        }

        result = db.get_pipeline_run(mock_table, user_id, "")

        assert result is not None
        assert result["status"] == "running"
        assert result["execution_arn"] == "arn:exec:123"
        mock_table.get_item.assert_called_once_with(
            Key={"PK": f"USER#{user_id}#PIPELINE", "SK": "LATEST"}
        )

    def test_returns_none_when_no_record(self, mock_table, user_id):
        mock_table.get_item.return_value = {}

        result = db.get_pipeline_run(mock_table, user_id, "")

        assert result is None

    def test_uses_correct_pk_format(self, mock_table, user_id):
        mock_table.get_item.return_value = {}

        db.get_pipeline_run(mock_table, user_id, "")

        key = mock_table.get_item.call_args[1]["Key"]
        assert key["PK"] == f"USER#{user_id}#PIPELINE"
        assert key["SK"] == "LATEST"


class TestPutPipelineRun:
    def test_writes_all_required_fields(self, mock_table, user_id):
        db.put_pipeline_run(mock_table, user_id, "", "arn:exec:new-123", "running")

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PIPELINE"
        assert item["SK"] == "LATEST"
        assert item["user_id"] == user_id
        assert item["execution_arn"] == "arn:exec:new-123"
        assert item["status"] == "running"
        assert "started_at" in item
        assert "updated_at" in item
        assert item["started_at"].endswith("Z")
        assert item["updated_at"].endswith("Z")

    def test_overwrites_existing_record(self, mock_table, user_id):
        """put_item overwrites — no conditional write."""
        db.put_pipeline_run(mock_table, user_id, "", "arn:exec:first", "running")
        mock_table.reset_mock()
        db.put_pipeline_run(mock_table, user_id, "", "arn:exec:second", "running")

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["execution_arn"] == "arn:exec:second"

    def test_stores_different_statuses(self, mock_table, user_id):
        db.put_pipeline_run(mock_table, user_id, "", "arn:exec:x", "succeeded")

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["status"] == "succeeded"


class TestUpdatePipelineStatus:
    def test_updates_status_and_timestamp(self, mock_table, user_id):
        db.update_pipeline_status(mock_table, user_id, "", "succeeded")

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#PIPELINE",
            "SK": "LATEST",
        }
        assert call_kwargs["ExpressionAttributeNames"] == {"#s": "status"}
        assert call_kwargs["ExpressionAttributeValues"][":s"] == "succeeded"
        assert call_kwargs["ExpressionAttributeValues"][":ts"].endswith("Z")

    def test_update_to_failed(self, mock_table, user_id):
        db.update_pipeline_status(mock_table, user_id, "", "failed")

        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["ExpressionAttributeValues"][":s"] == "failed"

    def test_update_expression_format(self, mock_table, user_id):
        db.update_pipeline_status(mock_table, user_id, "", "running")

        call_kwargs = mock_table.update_item.call_args[1]
        assert "SET #s = :s, updated_at = :ts" == call_kwargs["UpdateExpression"]

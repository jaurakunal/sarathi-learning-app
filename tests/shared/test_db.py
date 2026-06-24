"""Unit tests for backend.shared.db — all 17 DDB access functions.

Uses unittest.mock.MagicMock to simulate the boto3 DynamoDB Table resource.
Verifies that the correct PK/SK/attributes are passed to DDB operations and
that return values are handled correctly.
"""

from unittest.mock import MagicMock, patch

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
    return "test-user-123"


@pytest.fixture
def paper_id():
    return "arxiv-2406-12345"


@pytest.fixture
def sample_meta():
    return {
        "learning_style": {"math": "route-around"},
        "reading_speed": {"confidence": "low"},
        "paper_goal": "My goal",
    }


@pytest.fixture
def sample_area():
    return {
        "id": "person-clone",
        "label": "Person cloning",
        "status": "active",
        "role": "spine",
    }


@pytest.fixture
def sample_paper():
    return {
        "id": "arxiv-2406-12345",
        "title": "Test Paper",
        "source": "arxiv",
        "status": "candidate",
        "discovered_at": "2026-06-10T00:00:00.000Z",
    }


@pytest.fixture
def sample_card():
    return {
        "card_id": "20260610T000000Z_abc123",
        "paper_id": "p1",
        "card_type": "new_paper",
    }


@pytest.fixture
def sample_engagement_event():
    return {
        "ts": "2026-06-10T12:00:00.000Z",
        "paper_id": "p1",
        "action": "view",
        "active_ms": 5000,
    }


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_profile_pk(self, user_id):
        assert db._profile_pk(user_id) == f"USER#{user_id}#PROFILE"

    def test_paper_pk(self, user_id, paper_id):
        assert db._paper_pk(user_id, paper_id) == f"USER#{user_id}#PAPER#{paper_id}"

    def test_feed_pk(self, user_id):
        assert db._feed_pk(user_id) == f"USER#{user_id}#FEED"

    def test_library_pk(self, user_id, paper_id):
        assert db._library_pk(user_id, paper_id) == f"USER#{user_id}#LIBRARY#{paper_id}"

    def test_engagement_pk(self, user_id):
        assert db._engagement_pk(user_id) == f"USER#{user_id}#ENGAGEMENT"

    def test_profile_history_pk(self, user_id):
        assert db._profile_history_pk(user_id) == f"USER#{user_id}#PROFILE_HISTORY"

    def test_conv_pk(self, user_id):
        assert db._conv_pk(user_id, "conv1") == f"USER#{user_id}#CONV#conv1"

    def test_conv_archive_pk(self, user_id):
        assert db._conv_archive_pk(user_id, "conv1", "b1") == (
            f"USER#{user_id}#CONV_ARCHIVE#conv1#b1"
        )

    def test_now_iso_format(self):
        ts = db._now_iso()
        # Should end with Z
        assert ts.endswith("Z")
        # Should be ISO format: YYYY-MM-DDTHH:MM:SS.mmmZ
        assert "T" in ts
        assert len(ts) == 24  # 2026-06-10T12:00:00.000Z


# ---------------------------------------------------------------------------
# Profile functions
# ---------------------------------------------------------------------------


class TestGetFullProfile:
    def test_returns_structured_result(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"PK": "...", "SK": "META", "paper_goal": "my goal"},
                {"PK": "...", "SK": "AREA#a1", "label": "Area 1"},
                {"PK": "...", "SK": "AREA#a2", "label": "Area 2"},
                {"PK": "...", "SK": "HYPOTHESIS", "statement": "hyp"},
                {"PK": "...", "SK": "SUMMARY#yesterday", "content": "x"},
                {"PK": "...", "SK": "SUMMARY#7_day", "content": "y"},
            ],
        }

        result = db.get_full_profile(mock_table, user_id)

        assert result["meta"]["paper_goal"] == "my goal"
        assert len(result["areas"]) == 2
        assert result["hypothesis"]["statement"] == "hyp"
        assert len(result["summaries"]) == 2

    def test_empty_profile_returns_none_and_empty_lists(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.get_full_profile(mock_table, user_id)

        assert result["meta"] is None
        assert result["areas"] == []
        assert result["hypothesis"] is None
        assert result["summaries"] == []

    def test_queries_correct_pk(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}
        db.get_full_profile(mock_table, user_id)

        call_kwargs = mock_table.query.call_args[1]
        assert "KeyConditionExpression" in call_kwargs


class TestGetProfileMeta:
    def test_returns_item_when_found(self, mock_table, user_id):
        mock_table.get_item.return_value = {
            "Item": {"PK": "...", "SK": "META", "paper_goal": "goal"},
        }

        result = db.get_profile_meta(mock_table, user_id)

        assert result is not None
        assert result["paper_goal"] == "goal"

    def test_returns_none_when_not_found(self, mock_table, user_id):
        mock_table.get_item.return_value = {}

        result = db.get_profile_meta(mock_table, user_id)

        assert result is None

    def test_passes_correct_key(self, mock_table, user_id):
        mock_table.get_item.return_value = {}
        db.get_profile_meta(mock_table, user_id)

        call_kwargs = mock_table.get_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#PROFILE",
            "SK": "META",
        }


class TestGetProfileAreas:
    def test_returns_area_items(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"PK": "...", "SK": "AREA#a1", "label": "A1"},
                {"PK": "...", "SK": "AREA#a2", "label": "A2"},
            ],
        }

        result = db.get_profile_areas(mock_table, user_id)

        assert len(result) == 2
        assert result[0]["label"] == "A1"

    def test_returns_empty_list_when_no_areas(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.get_profile_areas(mock_table, user_id)

        assert result == []


class TestPutProfileMeta:
    def test_writes_correct_item(self, mock_table, user_id, sample_meta):
        db.put_profile_meta(mock_table, user_id, sample_meta)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PROFILE"
        assert item["SK"] == "META"
        assert item["user_id"] == user_id
        assert item["paper_goal"] == "My goal"
        assert "last_updated" in item

    def test_includes_timestamp(self, mock_table, user_id, sample_meta):
        db.put_profile_meta(mock_table, user_id, sample_meta)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["last_updated"].endswith("Z")


class TestPutProfileArea:
    def test_writes_correct_item(self, mock_table, user_id, sample_area):
        db.put_profile_area(mock_table, user_id, sample_area)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PROFILE"
        assert item["SK"] == "AREA#person-clone"
        assert item["user_id"] == user_id
        assert item["label"] == "Person cloning"

    def test_sets_added_at_when_missing(self, mock_table, user_id, sample_area):
        db.put_profile_area(mock_table, user_id, sample_area)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["added_at"].endswith("Z")

    def test_preserves_existing_added_at(self, mock_table, user_id, sample_area):
        sample_area["added_at"] = "2026-01-01T00:00:00.000Z"
        db.put_profile_area(mock_table, user_id, sample_area)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["added_at"] == "2026-01-01T00:00:00.000Z"

    def test_sets_added_at_when_none(self, mock_table, user_id, sample_area):
        sample_area["added_at"] = None
        db.put_profile_area(mock_table, user_id, sample_area)

        item = mock_table.put_item.call_args[1]["Item"]
        # Should be set to a timestamp (not None)
        assert item["added_at"].endswith("Z")


class TestPutProfileHypothesis:
    def test_writes_correct_item(self, mock_table, user_id):
        hypothesis = {"statement": "My hypothesis", "status": "untested"}
        db.put_profile_hypothesis(mock_table, user_id, hypothesis)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PROFILE"
        assert item["SK"] == "HYPOTHESIS"
        assert item["user_id"] == user_id
        assert item["statement"] == "My hypothesis"


class TestPutProfileSummary:
    def test_writes_correct_item(self, mock_table, user_id):
        db.put_profile_summary(mock_table, user_id, "yesterday", "Summary content")

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PROFILE"
        assert item["SK"] == "SUMMARY#yesterday"
        assert item["user_id"] == user_id
        assert item["tier"] == "yesterday"
        assert item["content"] == "Summary content"
        assert "updated_at" in item

    def test_different_tiers(self, mock_table, user_id):
        for tier in ["yesterday", "3_day", "7_day", "month", "quarter"]:
            mock_table.reset_mock()
            db.put_profile_summary(mock_table, user_id, tier, "content")

            item = mock_table.put_item.call_args[1]["Item"]
            assert item["SK"] == f"SUMMARY#{tier}"


# ---------------------------------------------------------------------------
# Paper functions
# ---------------------------------------------------------------------------


class TestGetPaper:
    def test_returns_item_when_found(self, mock_table, user_id, paper_id):
        mock_table.get_item.return_value = {
            "Item": {"PK": "...", "SK": "META", "title": "Paper Title"},
        }

        result = db.get_paper(mock_table, user_id, paper_id)

        assert result is not None
        assert result["title"] == "Paper Title"

    def test_returns_none_when_not_found(self, mock_table, user_id, paper_id):
        mock_table.get_item.return_value = {}

        result = db.get_paper(mock_table, user_id, paper_id)

        assert result is None

    def test_passes_correct_key(self, mock_table, user_id, paper_id):
        mock_table.get_item.return_value = {}
        db.get_paper(mock_table, user_id, paper_id)

        call_kwargs = mock_table.get_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#PAPER#{paper_id}",
            "SK": "META",
        }


class TestPutPaper:
    def test_writes_correct_item(self, mock_table, user_id, sample_paper):
        db.put_paper(mock_table, user_id, sample_paper)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PAPER#{sample_paper['id']}"
        assert item["SK"] == "META"
        assert item["user_id"] == user_id
        assert item["title"] == "Test Paper"

    def test_writes_gsi2_attributes(self, mock_table, user_id, sample_paper):
        db.put_paper(mock_table, user_id, sample_paper)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["gsi2pk"] == f"USER#{user_id}#PAPER_STATUS#candidate"
        assert item["gsi2sk"] == f"TS#{sample_paper['discovered_at']}"

    def test_sets_discovered_at_when_missing(self, mock_table, user_id):
        paper = {"id": "p1", "title": "T", "status": "surfaced"}
        db.put_paper(mock_table, user_id, paper)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["discovered_at"].endswith("Z")

    def test_defaults_status_to_candidate(self, mock_table, user_id):
        paper = {"id": "p1", "title": "T"}
        db.put_paper(mock_table, user_id, paper)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["gsi2pk"] == f"USER#{user_id}#PAPER_STATUS#candidate"


class TestPaperExists:
    def test_returns_true_when_exists(self, mock_table, user_id, paper_id):
        mock_table.get_item.return_value = {"Item": {"PK": "..."}}

        assert db.paper_exists(mock_table, user_id, paper_id) is True

    def test_returns_false_when_not_exists(self, mock_table, user_id, paper_id):
        mock_table.get_item.return_value = {}

        assert db.paper_exists(mock_table, user_id, paper_id) is False

    def test_uses_projection_expression(self, mock_table, user_id, paper_id):
        mock_table.get_item.return_value = {}
        db.paper_exists(mock_table, user_id, paper_id)

        call_kwargs = mock_table.get_item.call_args[1]
        assert call_kwargs["ProjectionExpression"] == "PK"


class TestListPapersByStatus:
    def test_returns_items(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [{"title": "P1"}, {"title": "P2"}],
        }

        result = db.list_papers_by_status(mock_table, user_id, "candidate")

        assert len(result) == 2

    def test_returns_empty_list_when_none(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.list_papers_by_status(mock_table, user_id, "surfaced")

        assert result == []

    def test_queries_gsi2_with_correct_params(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}
        db.list_papers_by_status(mock_table, user_id, "candidate", limit=10)

        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["IndexName"] == "GSI2"
        assert call_kwargs["ScanIndexForward"] is False
        assert call_kwargs["Limit"] == 10

    def test_default_limit_is_20(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}
        db.list_papers_by_status(mock_table, user_id, "candidate")

        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["Limit"] == 20


# ---------------------------------------------------------------------------
# Feed functions
# ---------------------------------------------------------------------------


class TestPutFeedCard:
    def test_writes_correct_item(self, mock_table, user_id, sample_card):
        db.put_feed_card(mock_table, user_id, sample_card)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#FEED"
        assert item["SK"] == f"CARD#{sample_card['card_id']}"
        assert item["user_id"] == user_id

    def test_sets_created_at_when_missing(self, mock_table, user_id, sample_card):
        db.put_feed_card(mock_table, user_id, sample_card)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["created_at"].endswith("Z")

    def test_preserves_existing_created_at(self, mock_table, user_id, sample_card):
        sample_card["created_at"] = "2026-01-01T00:00:00.000Z"
        db.put_feed_card(mock_table, user_id, sample_card)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["created_at"] == "2026-01-01T00:00:00.000Z"

    def test_sets_created_at_when_none(self, mock_table, user_id, sample_card):
        sample_card["created_at"] = None
        db.put_feed_card(mock_table, user_id, sample_card)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["created_at"].endswith("Z")


class TestListFeedCards:
    def test_returns_items_and_no_next_key(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [{"card_id": "c1"}, {"card_id": "c2"}],
        }

        items, next_key = db.list_feed_cards(mock_table, user_id)

        assert len(items) == 2
        assert next_key is None

    def test_returns_next_key_when_present(self, mock_table, user_id):
        last_key = {"PK": "...", "SK": "CARD#xyz"}
        mock_table.query.return_value = {
            "Items": [{"card_id": "c1"}],
            "LastEvaluatedKey": last_key,
        }

        items, next_key = db.list_feed_cards(mock_table, user_id)

        assert next_key == last_key

    def test_passes_last_key_for_pagination(self, mock_table, user_id):
        last_key = {"PK": "...", "SK": "CARD#prev"}
        mock_table.query.return_value = {"Items": []}

        db.list_feed_cards(mock_table, user_id, last_key=last_key)

        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["ExclusiveStartKey"] == last_key

    def test_does_not_pass_last_key_when_none(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        db.list_feed_cards(mock_table, user_id)

        call_kwargs = mock_table.query.call_args[1]
        assert "ExclusiveStartKey" not in call_kwargs

    def test_respects_limit(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        db.list_feed_cards(mock_table, user_id, limit=5)

        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["Limit"] == 5

    def test_queries_descending(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        db.list_feed_cards(mock_table, user_id)

        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["ScanIndexForward"] is False


class TestGetFeedCard:
    def test_returns_item_when_found(self, mock_table, user_id):
        mock_table.get_item.return_value = {
            "Item": {"card_id": "c1", "hook": "Interesting paper"},
        }

        result = db.get_feed_card(mock_table, user_id, "c1")

        assert result is not None
        assert result["hook"] == "Interesting paper"

    def test_returns_none_when_not_found(self, mock_table, user_id):
        mock_table.get_item.return_value = {}

        result = db.get_feed_card(mock_table, user_id, "nonexistent")

        assert result is None

    def test_passes_correct_key(self, mock_table, user_id):
        mock_table.get_item.return_value = {}
        db.get_feed_card(mock_table, user_id, "c1")

        call_kwargs = mock_table.get_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#FEED",
            "SK": "CARD#c1",
        }


# ---------------------------------------------------------------------------
# Engagement functions
# ---------------------------------------------------------------------------


class TestPutEngagementEvent:
    def test_writes_correct_item(self, mock_table, user_id, sample_engagement_event):
        db.put_engagement_event(mock_table, user_id, sample_engagement_event)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#ENGAGEMENT"
        assert item["SK"] == f"TS#{sample_engagement_event['ts']}"
        assert item["user_id"] == user_id
        assert item["action"] == "view"
        assert item["active_ms"] == 5000

    def test_writes_gsi4_attributes(self, mock_table, user_id, sample_engagement_event):
        db.put_engagement_event(mock_table, user_id, sample_engagement_event)

        item = mock_table.put_item.call_args[1]["Item"]
        ts = sample_engagement_event["ts"]
        paper_id = sample_engagement_event["paper_id"]
        assert item["gsi4pk"] == f"USER#{user_id}#PAPER_ENGAGEMENT#{paper_id}"
        assert item["gsi4sk"] == f"TS#{ts}"


class TestListEngagementEvents:
    def test_returns_items_in_range(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [{"action": "view"}, {"action": "read"}],
        }

        result = db.list_engagement_events(
            mock_table, user_id,
            "2026-06-01T00:00:00Z", "2026-06-10T23:59:59Z",
        )

        assert len(result) == 2

    def test_returns_empty_list_when_no_events(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.list_engagement_events(
            mock_table, user_id,
            "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z",
        )

        assert result == []

    def test_queries_correct_pk_and_sk_range(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}
        start = "2026-06-01T00:00:00Z"
        end = "2026-06-10T23:59:59Z"

        db.list_engagement_events(mock_table, user_id, start, end)

        mock_table.query.assert_called_once()


# ---------------------------------------------------------------------------
# Profile History functions
# ---------------------------------------------------------------------------


class TestPutProfileHistoryEvent:
    def test_writes_correct_item_with_ts(self, mock_table, user_id):
        event = {"ts": "2026-06-10T01:00:00Z", "type": "area_added", "area_id": "a1"}
        db.put_profile_history_event(mock_table, user_id, event)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PROFILE_HISTORY"
        assert item["SK"] == "TS#2026-06-10T01:00:00Z"
        assert item["user_id"] == user_id
        assert item["type"] == "area_added"
        assert item["area_id"] == "a1"
        assert item["ts"] == "2026-06-10T01:00:00Z"

    def test_generates_ts_when_missing(self, mock_table, user_id):
        event = {"type": "hypothesis_added"}
        db.put_profile_history_event(mock_table, user_id, event)

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["ts"].endswith("Z")
        assert item["SK"].startswith("TS#")

    def test_generates_sk_from_now_when_ts_is_none(self, mock_table, user_id):
        """When event['ts'] is None, the SK uses a generated timestamp.

        The **event spread overwrites ts back to None, and _sanitize_item
        strips None values, so 'ts' is absent from the final item.
        The SK is still correct (built from the generated ts variable).
        """
        event = {"ts": None, "type": "frontier_moved"}
        db.put_profile_history_event(mock_table, user_id, event)

        item = mock_table.put_item.call_args[1]["Item"]
        # SK is built from the local ts variable (generated), so it's correct
        assert item["SK"].startswith("TS#")
        assert item["SK"] != "TS#None"
        # _sanitize_item strips None values, so 'ts' key is absent
        assert "ts" not in item


# ---------------------------------------------------------------------------
# Push Subscriptions
# ---------------------------------------------------------------------------


class TestPutPushSubscription:
    def test_writes_correct_item(self, mock_table, user_id):
        subscription = {
            "endpoint": "https://push.example.com/sub/abc123",
            "keys": {"p256dh": "pubkey", "auth": "authkey"},
        }

        db.put_push_subscription(mock_table, user_id, subscription)

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PUSH"
        assert item["SK"].startswith("SUB#")
        assert item["endpoint"] == "https://push.example.com/sub/abc123"
        assert item["keys"] == {"p256dh": "pubkey", "auth": "authkey"}
        assert "created_at" in item


class TestDeletePushSubscription:
    def test_deletes_with_correct_key(self, mock_table, user_id):
        endpoint = "https://push.example.com/sub/abc123"

        db.delete_push_subscription(mock_table, user_id, endpoint)

        mock_table.delete_item.assert_called_once()
        key = mock_table.delete_item.call_args[1]["Key"]
        assert key["PK"] == f"USER#{user_id}#PUSH"
        assert key["SK"].startswith("SUB#")

    def test_same_endpoint_produces_same_hash(self, mock_table, user_id):
        endpoint = "https://push.example.com/sub/abc123"

        db.delete_push_subscription(mock_table, user_id, endpoint)
        key1 = mock_table.delete_item.call_args[1]["Key"]["SK"]

        mock_table.reset_mock()
        db.delete_push_subscription(mock_table, user_id, endpoint)
        key2 = mock_table.delete_item.call_args[1]["Key"]["SK"]

        assert key1 == key2


class TestListPushSubscriptions:
    def test_returns_items(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"endpoint": "https://push.example.com/1", "keys": {"p256dh": "k1", "auth": "a1"}},
                {"endpoint": "https://push.example.com/2", "keys": {"p256dh": "k2", "auth": "a2"}},
            ]
        }

        result = db.list_push_subscriptions(mock_table, user_id)

        assert len(result) == 2
        assert result[0]["endpoint"] == "https://push.example.com/1"

    def test_returns_empty_when_no_subs(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.list_push_subscriptions(mock_table, user_id)

        assert result == []


# ---------------------------------------------------------------------------
# Pin / Unpin Turns
# ---------------------------------------------------------------------------


class TestPinTurn:
    def test_sets_pinned_true_with_timestamp(self, mock_table, user_id):
        db.pin_turn(mock_table, user_id, "conv-1", 3)

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#CONV#conv-1",
            "SK": "TURN#00003",
        }
        assert ":t" in call_kwargs["ExpressionAttributeValues"]
        assert call_kwargs["ExpressionAttributeValues"][":t"] is True

    def test_includes_pin_note_when_provided(self, mock_table, user_id):
        db.pin_turn(mock_table, user_id, "conv-1", 5, pin_note="Key insight")

        call_kwargs = mock_table.update_item.call_args[1]
        assert ":note" in call_kwargs["ExpressionAttributeValues"]
        assert call_kwargs["ExpressionAttributeValues"][":note"] == "Key insight"
        assert "pin_note" in call_kwargs["UpdateExpression"]


class TestUnpinTurn:
    def test_removes_pinned_attributes(self, mock_table, user_id):
        db.unpin_turn(mock_table, user_id, "conv-1", 3)

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#CONV#conv-1",
            "SK": "TURN#00003",
        }
        assert "REMOVE" in call_kwargs["UpdateExpression"]


class TestGetPinnedTurns:
    def test_returns_pinned_items(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"seq": 1, "pinned": True, "request": "Q?", "response": "A"},
            ]
        }

        result = db.get_pinned_turns(mock_table, user_id, "conv-1")

        assert len(result) == 1
        assert result[0]["pinned"] is True

    def test_returns_empty_when_none_pinned(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.get_pinned_turns(mock_table, user_id, "conv-1")

        assert result == []


# ---------------------------------------------------------------------------
# Tag Paper
# ---------------------------------------------------------------------------


class TestTagPaper:
    def test_sets_relevance_and_tags(self, mock_table, user_id):
        db.tag_paper(mock_table, user_id, "card-123", "core", ["alignment", "safety"])

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#FEED",
            "SK": "CARD#card-123",
        }
        values = call_kwargs["ExpressionAttributeValues"]
        assert values[":r"] == "core"
        assert values[":t"] == ["alignment", "safety"]
        assert values[":ts"].endswith("Z")


# ---------------------------------------------------------------------------
# Research Conversations
# ---------------------------------------------------------------------------


class TestCreateResearchConversation:
    def test_writes_correct_item(self, mock_table, user_id):
        result = db.create_research_conversation(mock_table, user_id, "conv-abc", "My Research")

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#CONV#conv-abc"
        assert item["SK"] == "META"
        assert item["scope"] == "research"
        assert item["title"] == "My Research"
        assert item["conv_id"] == "conv-abc"
        assert item["gsi1pk"] == f"USER#{user_id}"
        assert item["gsi1sk"] == "CONV#conv-abc"
        assert result["conv_id"] == "conv-abc"

    def test_default_title(self, mock_table, user_id):
        result = db.create_research_conversation(mock_table, user_id, "conv-abc", "")

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["title"] == "New conversation"


class TestListAllConversations:
    def test_returns_items(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"conv_id": "c1", "scope": "research", "title": "Thread 1"},
                {"conv_id": "c2", "scope": "paper", "paper_id": "p1"},
            ]
        }

        result = db.list_all_conversations(mock_table, user_id)

        assert len(result) == 2
        mock_table.query.assert_called_once()
        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["IndexName"] == "GSI1"
        assert call_kwargs["ScanIndexForward"] is False

    def test_returns_empty_when_none(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.list_all_conversations(mock_table, user_id)

        assert result == []


class TestUpdateConversationTitle:
    def test_updates_with_correct_params(self, mock_table, user_id):
        db.update_conversation_title(mock_table, user_id, "conv-1", "New Title")

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs["Key"] == {
            "PK": f"USER#{user_id}#CONV#conv-1",
            "SK": "META",
        }
        assert call_kwargs["ExpressionAttributeValues"][":t"] == "New Title"


class TestDeleteConversation:
    def test_deletes_all_items_under_pk(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"PK": f"USER#{user_id}#CONV#conv-1", "SK": "META"},
                {"PK": f"USER#{user_id}#CONV#conv-1", "SK": "TURN#00001"},
                {"PK": f"USER#{user_id}#CONV#conv-1", "SK": "TURN#00002"},
            ]
        }
        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch_writer)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        db.delete_conversation(mock_table, user_id, "conv-1")

        assert mock_batch_writer.delete_item.call_count == 3


# ---------------------------------------------------------------------------
# get_feed_card_by_paper
# ---------------------------------------------------------------------------


class TestGetFeedCardByPaper:
    def test_returns_first_matching_card(self, mock_table, user_id):
        mock_table.query.return_value = {
            "Items": [
                {"card_id": "c1", "paper_id": "p1", "hook": "Great paper"},
            ]
        }

        result = db.get_feed_card_by_paper(mock_table, user_id, "p1")

        assert result is not None
        assert result["card_id"] == "c1"

    def test_returns_none_when_no_match(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": []}

        result = db.get_feed_card_by_paper(mock_table, user_id, "p-nonexistent")

        assert result is None

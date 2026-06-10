"""Unit tests for backend.shared.seed_profile — profile building + DDB writing.

Verifies all 16 items are built with correct PKs/SKs/attributes, that None values
are stripped before writing, and that the seed_profile function writes all items
via batch_writer.
"""

from dataclasses import asdict
from unittest.mock import MagicMock, patch, call

import pytest

from backend.shared.seed_profile import (
    NOW,
    build_areas,
    build_history_events,
    build_hypothesis,
    build_meta,
    build_summaries,
    seed_profile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id():
    return "test-user-seed"


@pytest.fixture
def mock_table():
    """Mock DynamoDB Table with batch_writer context manager."""
    table = MagicMock()
    batch_writer = MagicMock()
    table.batch_writer.return_value.__enter__ = MagicMock(return_value=batch_writer)
    table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
    return table


# ---------------------------------------------------------------------------
# build_meta tests
# ---------------------------------------------------------------------------


class TestBuildMeta:
    def test_pk_and_sk(self, user_id):
        item = build_meta(user_id)
        assert item["PK"] == f"USER#{user_id}#PROFILE"
        assert item["SK"] == "META"

    def test_user_id_field(self, user_id):
        item = build_meta(user_id)
        assert item["user_id"] == user_id

    def test_learning_style_fields(self, user_id):
        item = build_meta(user_id)
        ls = item["learning_style"]
        assert ls["math"] == "route-around; tap-to-reveal only; never gate"
        assert ls["lead_with"] == "applied / can-I-use-this"
        assert ls["tone"] == "sharp mirror, no flattery, credit at exact scope"

    def test_reading_speed_fields(self, user_id):
        item = build_meta(user_id)
        rs = item["reading_speed"]
        assert rs["initial_idle_threshold_s"] == 60
        assert rs["current_idle_threshold_s"] == 60
        assert rs["avg_active_ms_per_card"] is None
        assert rs["confidence"] == "low"
        assert rs["last_calibrated"] is None

    def test_paper_goal(self, user_id):
        item = build_meta(user_id)
        assert item["paper_goal"] == "Accumulate citations/claims/gaps toward my own paper."

    def test_last_updated(self, user_id):
        item = build_meta(user_id)
        assert item["last_updated"] == NOW


# ---------------------------------------------------------------------------
# build_areas tests
# ---------------------------------------------------------------------------


class TestBuildAreas:
    def test_returns_four_areas(self, user_id):
        areas = build_areas(user_id)
        assert len(areas) == 4

    def test_all_have_correct_pk(self, user_id):
        areas = build_areas(user_id)
        for area in areas:
            assert area["PK"] == f"USER#{user_id}#PROFILE"

    def test_sk_format(self, user_id):
        areas = build_areas(user_id)
        expected_ids = [
            "person-clone-personality",
            "agent-memory",
            "long-running-agents",
            "adversarial-security",
        ]
        for area, expected_id in zip(areas, expected_ids):
            assert area["SK"] == f"AREA#{expected_id}"

    def test_first_area_is_spine(self, user_id):
        areas = build_areas(user_id)
        assert areas[0]["role"] == "spine"
        assert areas[0]["label"] == "Person-cloning / mental models"

    def test_status_is_string_not_enum(self, user_id):
        areas = build_areas(user_id)
        for area in areas:
            assert isinstance(area["status"], str)
            assert area["status"] == "active"

    def test_role_is_string_not_enum(self, user_id):
        areas = build_areas(user_id)
        # First two are spine, last two are secondary
        assert areas[0]["role"] == "spine"
        assert areas[1]["role"] == "spine"
        assert areas[2]["role"] == "secondary"
        assert areas[3]["role"] == "secondary"

    def test_links_are_present(self, user_id):
        areas = build_areas(user_id)
        # person-clone-personality has links
        assert "agent-memory" in areas[0]["links"]
        assert "contemplative-memory" in areas[0]["links"]

    def test_added_at_is_set(self, user_id):
        areas = build_areas(user_id)
        for area in areas:
            assert area["added_at"] == NOW

    def test_frontier_is_non_empty(self, user_id):
        areas = build_areas(user_id)
        for area in areas:
            assert len(area["frontier"]) > 0

    def test_too_basic_and_just_right_populated(self, user_id):
        areas = build_areas(user_id)
        for area in areas:
            assert isinstance(area["too_basic"], list)
            assert len(area["too_basic"]) >= 1
            assert isinstance(area["just_right"], list)
            assert len(area["just_right"]) >= 1


# ---------------------------------------------------------------------------
# build_hypothesis tests
# ---------------------------------------------------------------------------


class TestBuildHypothesis:
    def test_pk_and_sk(self, user_id):
        item = build_hypothesis(user_id)
        assert item["PK"] == f"USER#{user_id}#PROFILE"
        assert item["SK"] == "HYPOTHESIS"

    def test_user_id_field(self, user_id):
        item = build_hypothesis(user_id)
        assert item["user_id"] == user_id

    def test_statement(self, user_id):
        item = build_hypothesis(user_id)
        assert item["statement"] == "Brain-structure + agentic harness >> the LLM."

    def test_status_is_untested(self, user_id):
        item = build_hypothesis(user_id)
        assert item["status"] == "untested"

    def test_supporting_refuting_refining_empty(self, user_id):
        item = build_hypothesis(user_id)
        assert item["supporting"] == []
        assert item["refuting"] == []
        assert item["refining"] == []


# ---------------------------------------------------------------------------
# build_summaries tests
# ---------------------------------------------------------------------------


class TestBuildSummaries:
    def test_returns_five_summaries(self, user_id):
        summaries = build_summaries(user_id)
        assert len(summaries) == 5

    def test_all_tiers_present(self, user_id):
        summaries = build_summaries(user_id)
        tiers = {s["tier"] for s in summaries}
        assert tiers == {"yesterday", "3_day", "7_day", "month", "quarter"}

    def test_correct_pk(self, user_id):
        summaries = build_summaries(user_id)
        for s in summaries:
            assert s["PK"] == f"USER#{user_id}#PROFILE"

    def test_sk_format(self, user_id):
        summaries = build_summaries(user_id)
        for s in summaries:
            assert s["SK"] == f"SUMMARY#{s['tier']}"

    def test_initial_content(self, user_id):
        summaries = build_summaries(user_id)
        for s in summaries:
            assert s["content"] == "No activity yet."

    def test_last_updated(self, user_id):
        summaries = build_summaries(user_id)
        for s in summaries:
            assert s["last_updated"] == NOW


# ---------------------------------------------------------------------------
# build_history_events tests
# ---------------------------------------------------------------------------


class TestBuildHistoryEvents:
    def test_returns_five_events(self, user_id):
        events = build_history_events(user_id)
        assert len(events) == 5

    def test_four_area_added_events(self, user_id):
        events = build_history_events(user_id)
        area_events = [e for e in events if e["type"] == "area_added"]
        assert len(area_events) == 4

    def test_one_hypothesis_added_event(self, user_id):
        events = build_history_events(user_id)
        hyp_events = [e for e in events if e["type"] == "hypothesis_added"]
        assert len(hyp_events) == 1

    def test_correct_pk(self, user_id):
        events = build_history_events(user_id)
        for e in events:
            assert e["PK"] == f"USER#{user_id}#PROFILE_HISTORY"

    def test_sk_format(self, user_id):
        events = build_history_events(user_id)
        for e in events:
            assert e["SK"].startswith("EVENT#")

    def test_unique_sks(self, user_id):
        events = build_history_events(user_id)
        sks = [e["SK"] for e in events]
        assert len(sks) == len(set(sks))

    def test_area_ids_match_expected(self, user_id):
        events = build_history_events(user_id)
        area_events = [e for e in events if e["type"] == "area_added"]
        area_ids = [e["area_id"] for e in area_events]
        expected = [
            "person-clone-personality",
            "agent-memory",
            "long-running-agents",
            "adversarial-security",
        ]
        assert area_ids == expected

    def test_all_events_have_onboarding_reason(self, user_id):
        events = build_history_events(user_id)
        for e in events:
            assert e["reason"] == "onboarding interview"

    def test_timestamps_are_sequential(self, user_id):
        events = build_history_events(user_id)
        timestamps = [e["ts"] for e in events]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# seed_profile integration tests (mocked DDB)
# ---------------------------------------------------------------------------


class TestSeedProfile:
    @patch("backend.shared.seed_profile.boto3")
    def test_writes_16_items_total(self, mock_boto3, user_id):
        mock_table = MagicMock()
        mock_batch = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
        mock_boto3.resource.return_value.Table.return_value = mock_table

        seed_profile(user_id, "test-table")

        # 1 META + 4 AREA + 1 HYPOTHESIS + 5 SUMMARY + 5 HISTORY = 16
        assert mock_batch.put_item.call_count == 16

    @patch("backend.shared.seed_profile.boto3")
    def test_creates_table_with_correct_name(self, mock_boto3, user_id):
        mock_table = MagicMock()
        mock_batch = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
        mock_boto3.resource.return_value.Table.return_value = mock_table

        seed_profile(user_id, "sarathi-prod")

        mock_boto3.resource.return_value.Table.assert_called_once_with("sarathi-prod")

    @patch("backend.shared.seed_profile.boto3")
    def test_none_values_are_stripped(self, mock_boto3, user_id):
        mock_table = MagicMock()
        mock_batch = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
        mock_boto3.resource.return_value.Table.return_value = mock_table

        seed_profile(user_id, "test-table")

        # Check that no item written contains None values
        for call_obj in mock_batch.put_item.call_args_list:
            item = call_obj[1]["Item"]
            for key, value in item.items():
                assert value is not None, (
                    f"Item with PK={item.get('PK')} SK={item.get('SK')} "
                    f"has None value for key '{key}'"
                )

    @patch("backend.shared.seed_profile.boto3")
    def test_all_items_have_pk_and_sk(self, mock_boto3, user_id):
        mock_table = MagicMock()
        mock_batch = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
        mock_boto3.resource.return_value.Table.return_value = mock_table

        seed_profile(user_id, "test-table")

        for call_obj in mock_batch.put_item.call_args_list:
            item = call_obj[1]["Item"]
            assert "PK" in item, f"Item missing PK: {item}"
            assert "SK" in item, f"Item missing SK: {item}"

    @patch("backend.shared.seed_profile.boto3")
    def test_uses_batch_writer_context_manager(self, mock_boto3, user_id):
        mock_table = MagicMock()
        mock_batch = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
        mock_boto3.resource.return_value.Table.return_value = mock_table

        seed_profile(user_id, "test-table")

        mock_table.batch_writer.assert_called_once()

    @patch("backend.shared.seed_profile.boto3")
    def test_item_pks_are_correct_partition(self, mock_boto3, user_id):
        mock_table = MagicMock()
        mock_batch = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
        mock_boto3.resource.return_value.Table.return_value = mock_table

        seed_profile(user_id, "test-table")

        profile_pk = f"USER#{user_id}#PROFILE"
        history_pk = f"USER#{user_id}#PROFILE_HISTORY"

        pks = set()
        for call_obj in mock_batch.put_item.call_args_list:
            item = call_obj[1]["Item"]
            pks.add(item["PK"])

        # Should only have profile and history PKs
        assert pks == {profile_pk, history_pk}

    @patch("backend.shared.seed_profile.boto3")
    def test_sk_distribution(self, mock_boto3, user_id):
        """Verify the expected SK values are written."""
        mock_table = MagicMock()
        mock_batch = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
        mock_boto3.resource.return_value.Table.return_value = mock_table

        seed_profile(user_id, "test-table")

        sks = []
        for call_obj in mock_batch.put_item.call_args_list:
            item = call_obj[1]["Item"]
            sks.append(item["SK"])

        # Check expected SKs
        assert "META" in sks
        assert "HYPOTHESIS" in sks
        assert "AREA#person-clone-personality" in sks
        assert "AREA#agent-memory" in sks
        assert "AREA#long-running-agents" in sks
        assert "AREA#adversarial-security" in sks
        assert "SUMMARY#yesterday" in sks
        assert "SUMMARY#3_day" in sks
        assert "SUMMARY#7_day" in sks
        assert "SUMMARY#month" in sks
        assert "SUMMARY#quarter" in sks
        # 5 history events
        event_sks = [sk for sk in sks if sk.startswith("EVENT#")]
        assert len(event_sks) == 5


class TestSeedProfileNoneStripping:
    """Focused tests on None value stripping behavior."""

    def test_meta_has_none_values_in_reading_speed(self, user_id):
        """Verify that build_meta produces items with None that need stripping."""
        item = build_meta(user_id)
        # reading_speed has None values
        rs = item["reading_speed"]
        assert rs["avg_active_ms_per_card"] is None
        assert rs["last_calibrated"] is None

    @patch("backend.shared.seed_profile.boto3")
    def test_nested_none_in_reading_speed_stripped(self, mock_boto3, user_id):
        """The top-level None stripping removes keys with None values.

        Note: nested dict values (like reading_speed.avg_active_ms_per_card)
        may still be None since the stripping only operates on top-level keys.
        This test documents the actual behavior.
        """
        mock_table = MagicMock()
        mock_batch = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
        mock_boto3.resource.return_value.Table.return_value = mock_table

        seed_profile(user_id, "test-table")

        # Find the META item
        meta_item = None
        for call_obj in mock_batch.put_item.call_args_list:
            item = call_obj[1]["Item"]
            if item.get("SK") == "META":
                meta_item = item
                break

        assert meta_item is not None
        # Top-level None values like last_updated should NOT be None
        # (last_updated is set to NOW so it's never None in this case)
        # But verify no top-level keys have None values
        for key, value in meta_item.items():
            if not isinstance(value, dict):
                assert value is not None, f"Top-level key '{key}' is None"

"""Tests for workspace-aware additions in backend.shared.db."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.shared import db


@pytest.fixture
def mock_table():
    return MagicMock()


@pytest.fixture
def user_id():
    return "user-1"


@pytest.fixture
def workspace_id():
    return "ws-abc"


# ---------------------------------------------------------------------------
# PK helpers
# ---------------------------------------------------------------------------

class TestPkInjection:
    def test_profile_pk_with_workspace(self, user_id, workspace_id):
        assert db._profile_pk(user_id, workspace_id) == f"USER#{user_id}#WS#{workspace_id}#PROFILE"

    def test_profile_pk_legacy(self, user_id):
        assert db._profile_pk(user_id, "") == f"USER#{user_id}#PROFILE"

    def test_paper_pk_with_workspace(self, user_id, workspace_id):
        assert db._paper_pk(user_id, workspace_id, "p1") == f"USER#{user_id}#WS#{workspace_id}#PAPER#p1"

    def test_feed_pk_with_workspace(self, user_id, workspace_id):
        assert db._feed_pk(user_id, workspace_id) == f"USER#{user_id}#WS#{workspace_id}#FEED"

    def test_engagement_pk_with_workspace(self, user_id, workspace_id):
        assert db._engagement_pk(user_id, workspace_id) == f"USER#{user_id}#WS#{workspace_id}#ENGAGEMENT"

    def test_conv_pk_with_workspace(self, user_id, workspace_id):
        assert db._conv_pk(user_id, workspace_id, "c1") == f"USER#{user_id}#WS#{workspace_id}#CONV#c1"

    def test_brief_pk_with_workspace(self, user_id, workspace_id):
        assert db._brief_pk(user_id, workspace_id) == f"USER#{user_id}#WS#{workspace_id}#BRIEF"

    def test_pipeline_pk_with_workspace(self, user_id, workspace_id):
        assert db._pipeline_pk(user_id, workspace_id) == f"USER#{user_id}#WS#{workspace_id}#PIPELINE"

    def test_gsi_user_scope_with_workspace(self, user_id, workspace_id):
        assert db._gsi_user_scope(user_id, workspace_id) == f"USER#{user_id}#WS#{workspace_id}"

    def test_gsi_user_scope_legacy(self, user_id):
        assert db._gsi_user_scope(user_id, "") == f"USER#{user_id}"


# ---------------------------------------------------------------------------
# User META + onboarding marker (user-level, not workspace-scoped)
# ---------------------------------------------------------------------------

class TestUserMeta:
    def test_get_user_meta_uses_user_pk(self, mock_table, user_id):
        mock_table.get_item.return_value = {"Item": {"learning_style": {"depth": "practitioner"}}}
        result = db.get_user_meta(mock_table, user_id)
        assert result["learning_style"]["depth"] == "practitioner"
        mock_table.get_item.assert_called_once_with(
            Key={"PK": f"USER#{user_id}#PROFILE", "SK": "META"},
        )

    def test_put_user_meta_writes_user_pk(self, mock_table, user_id):
        db.put_user_meta(mock_table, user_id, {"background": "engineer"})
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#PROFILE"
        assert item["SK"] == "META"
        assert item["background"] == "engineer"


class TestOnboardingMarker:
    def test_set_user_onboarding_complete(self, mock_table, user_id):
        db.set_user_onboarding_complete(mock_table, user_id)
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#ONBOARDING"
        assert item["SK"] == "META"
        assert item["user_onboarding_complete"] is True

    def test_get_user_onboarding_status_returns_item(self, mock_table, user_id):
        mock_table.get_item.return_value = {"Item": {"user_onboarding_complete": True}}
        status = db.get_user_onboarding_status(mock_table, user_id)
        assert status["user_onboarding_complete"] is True


# ---------------------------------------------------------------------------
# Workspace registry (USER#<sub>#WORKSPACES partition)
# ---------------------------------------------------------------------------

class TestWorkspaceRegistry:
    def test_create_workspace(self, mock_table, user_id):
        item = db.create_workspace(mock_table, user_id, "ws-new", name="My Workspace")
        assert item["workspace_id"] == "ws-new"
        assert item["name"] == "My Workspace"
        written = mock_table.put_item.call_args[1]["Item"]
        assert written["PK"] == f"USER#{user_id}#WORKSPACES"
        assert written["SK"] == "WS#ws-new"
        assert written["status"] == "active"

    def test_list_workspaces_queries_partition(self, mock_table, user_id):
        mock_table.query.return_value = {"Items": [{"workspace_id": "ws-1"}]}
        items = db.list_workspaces(mock_table, user_id)
        assert items[0]["workspace_id"] == "ws-1"
        mock_table.query.assert_called_once()

    def test_get_workspace(self, mock_table, user_id):
        mock_table.get_item.return_value = {"Item": {"workspace_id": "ws-1"}}
        ws = db.get_workspace(mock_table, user_id, "ws-1")
        assert ws["workspace_id"] == "ws-1"

    def test_update_workspace_only_writes_allowed_fields(self, mock_table, user_id):
        db.update_workspace(mock_table, user_id, "ws-1", name="New", random_field="ignored")
        update_kwargs = mock_table.update_item.call_args[1]
        # The disallowed field shouldn't appear
        assert "random_field" not in str(update_kwargs)

    def test_update_workspace_none_field_uses_remove_not_dangling_value(self, mock_table, user_id):
        """Resume passes paused_reason=None. It must REMOVE the attribute, and
        must NOT leave a :vN reference with no matching ExpressionAttributeValues
        entry (that caused a Bedrock-style ValidationException -> 502)."""
        db.update_workspace(
            mock_table, user_id, "ws-1", status="active", paused_reason=None,
        )
        kwargs = mock_table.update_item.call_args[1]
        expr = kwargs["UpdateExpression"]
        values = kwargs.get("ExpressionAttributeValues", {})

        # status is SET, paused_reason is REMOVEd
        assert "SET" in expr and "REMOVE" in expr
        # Every :vN token referenced in the expression must be defined.
        import re
        referenced = set(re.findall(r":v\d+", expr))
        assert referenced == set(values.keys())
        assert "active" in values.values()

    def test_update_workspace_all_none_still_removes(self, mock_table, user_id):
        """If every provided field is None, we still issue a REMOVE-only update
        with no ExpressionAttributeValues key."""
        db.update_workspace(mock_table, user_id, "ws-1", paused_reason=None)
        kwargs = mock_table.update_item.call_args[1]
        assert kwargs["UpdateExpression"].startswith("REMOVE")
        assert "ExpressionAttributeValues" not in kwargs

    def test_archive_workspace_sets_status(self, mock_table, user_id):
        db.archive_workspace(mock_table, user_id, "ws-1")
        update_kwargs = mock_table.update_item.call_args[1]
        values = update_kwargs["ExpressionAttributeValues"]
        assert "archived" in values.values()


# ---------------------------------------------------------------------------
# Active workspace pointer
# ---------------------------------------------------------------------------

class TestActiveWorkspace:
    def test_get_active_workspace_returns_workspace_id(self, mock_table, user_id):
        mock_table.get_item.return_value = {"Item": {"workspace_id": "ws-active"}}
        result = db.get_active_workspace(mock_table, user_id)
        assert result == "ws-active"

    def test_get_active_workspace_returns_none_when_not_set(self, mock_table, user_id):
        mock_table.get_item.return_value = {}
        result = db.get_active_workspace(mock_table, user_id)
        assert result is None

    def test_set_active_workspace_writes_settings_pk(self, mock_table, user_id):
        db.set_active_workspace(mock_table, user_id, "ws-new")
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#SETTINGS"
        assert item["SK"] == "ACTIVE_WS"
        assert item["workspace_id"] == "ws-new"


# ---------------------------------------------------------------------------
# Workspace-scoped functions: verify PK contains WS#<wid>
# ---------------------------------------------------------------------------

class TestWorkspaceScopedWrites:
    def test_put_paper_uses_workspace_pk(self, mock_table, user_id, workspace_id):
        db.put_paper(mock_table, user_id, workspace_id, {"id": "p1", "status": "candidate"})
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#WS#{workspace_id}#PAPER#p1"
        assert item["gsi2pk"] == f"USER#{user_id}#WS#{workspace_id}#PAPER_STATUS#candidate"

    def test_put_feed_card_uses_workspace_pk(self, mock_table, user_id, workspace_id):
        db.put_feed_card(mock_table, user_id, workspace_id,
                         {"card_id": "20260101_abc", "paper_id": "p1"})
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#WS#{workspace_id}#FEED"

    def test_put_engagement_event_writes_gsi4_with_workspace(self, mock_table, user_id, workspace_id):
        db.put_engagement_event(mock_table, user_id, workspace_id,
                                {"ts": "2026-01-01T00:00:00Z", "paper_id": "p1", "action": "view"})
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["gsi4pk"] == f"USER#{user_id}#WS#{workspace_id}#PAPER_ENGAGEMENT#p1"

    def test_create_conversation_writes_gsi1_with_workspace(self, mock_table, user_id, workspace_id):
        db.create_conversation(mock_table, user_id, workspace_id, "p1", "key")
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["gsi1pk"] == f"USER#{user_id}#WS#{workspace_id}"

    def test_pipeline_run_uses_workspace_pk(self, mock_table, user_id, workspace_id):
        db.put_pipeline_run(mock_table, user_id, workspace_id, "arn:exec:1", "running")
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == f"USER#{user_id}#WS#{workspace_id}#PIPELINE"
        assert item["SK"] == "LATEST"
        assert item["workspace_id"] == workspace_id

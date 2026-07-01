"""Tests for scripts.migrate_workspaces."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_table():
    return MagicMock()


@pytest.fixture
def user_id():
    return "user-1"


def test_split_meta_separates_user_and_workspace_fields():
    from scripts.migrate_workspaces import _split_meta

    legacy = {
        "PK": "USER#u1#PROFILE",
        "SK": "META",
        "user_id": "u1",
        "last_updated": "2026-01-01",
        "learning_style": {"depth": "practitioner"},
        "background": "engineer",
        "math_comfort": "tolerate",
        "paper_preference": "applied",
        "paper_goal": "build a clone",
        "hypothesis_brief": "harness > LLM",
    }
    user, workspace = _split_meta(legacy)

    assert user == {
        "learning_style": {"depth": "practitioner"},
        "background": "engineer",
        "math_comfort": "tolerate",
        "paper_preference": "applied",
    }
    assert workspace == {
        "paper_goal": "build a clone",
        "hypothesis_brief": "harness > LLM",
    }


def test_split_meta_drops_ddb_internal_keys():
    from scripts.migrate_workspaces import _split_meta
    user, workspace = _split_meta({"PK": "x", "SK": "y", "user_id": "u"})
    assert user == {}
    assert workspace == {}


def test_split_meta_handles_empty_input():
    from scripts.migrate_workspaces import _split_meta
    user, workspace = _split_meta({})
    assert user == {}
    assert workspace == {}


@patch("scripts.migrate_workspaces.db")
def test_migrate_user_skips_when_workspace_already_exists(mock_db, mock_table, user_id):
    from scripts.migrate_workspaces import migrate_user

    mock_db.list_workspaces.return_value = [{"workspace_id": "existing-ws"}]
    summary = migrate_user(mock_table, user_id, apply=False)

    assert summary["skipped"] is True
    assert summary["workspace_id"] == "existing-ws"


@patch("scripts.migrate_workspaces.db")
def test_migrate_user_dry_run_does_not_write(mock_db, mock_table, user_id):
    from scripts.migrate_workspaces import migrate_user

    mock_db.list_workspaces.return_value = []

    summary = migrate_user(mock_table, user_id, apply=False)

    assert summary["skipped"] is False
    assert summary["workspace_id"] is not None
    # Dry run: db.create_workspace and put_user_meta MUST NOT be called.
    mock_db.create_workspace.assert_not_called()
    mock_db.put_user_meta.assert_not_called()
    mock_db.set_active_workspace.assert_not_called()


@patch("scripts.migrate_workspaces.db")
def test_migrate_user_apply_creates_workspace_and_pointer(mock_db, mock_table, user_id):
    from scripts.migrate_workspaces import migrate_user

    mock_db.list_workspaces.return_value = []
    # Simulate empty legacy data
    mock_table.query.return_value = {"Items": []}
    mock_table.get_item.return_value = {}

    summary = migrate_user(mock_table, user_id, apply=True)

    assert summary["skipped"] is False
    mock_db.create_workspace.assert_called_once()
    mock_db.set_active_workspace.assert_called_once()
    mock_db.set_user_onboarding_complete.assert_called_once()


@patch("scripts.migrate_workspaces.db")
def test_migrate_user_copies_areas(mock_db, mock_table, user_id):
    from scripts.migrate_workspaces import migrate_user

    mock_db.list_workspaces.return_value = []

    # Helper to return area items for the legacy profile query
    def query_side(**kwargs):
        cond = str(kwargs.get("KeyConditionExpression"))
        if "PROFILE" in cond and "FEED" not in cond:
            return {"Items": [
                {"PK": "USER#u1#PROFILE", "SK": "META",
                 "learning_style": {"depth": "practitioner"}, "paper_goal": "x"},
                {"PK": "USER#u1#PROFILE", "SK": "AREA#a1", "id": "a1", "label": "Area 1"},
                {"PK": "USER#u1#PROFILE", "SK": "AREA#a2", "id": "a2", "label": "Area 2"},
                {"PK": "USER#u1#PROFILE", "SK": "HYPOTHESIS",
                 "statement": "harness > LLM"},
            ]}
        return {"Items": []}

    mock_table.query.side_effect = query_side
    mock_table.get_item.return_value = {}

    summary = migrate_user(mock_table, user_id, apply=True)

    assert summary["areas"] == 2
    # User-level meta got the learning_style; workspace meta got the paper_goal
    user_meta_calls = mock_db.put_user_meta.call_args_list
    assert len(user_meta_calls) == 1
    user_payload = user_meta_calls[0][0][2]
    assert "learning_style" in user_payload
    # Hypothesis was copied
    mock_db.put_profile_hypothesis.assert_called_once()


def test_new_workspace_id_returns_string():
    from scripts.migrate_workspaces import _new_workspace_id
    wid = _new_workspace_id()
    assert isinstance(wid, str)
    assert len(wid) > 10

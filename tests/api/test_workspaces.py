"""Tests for backend.api.workspaces — workspace CRUD endpoints."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def _event(method, path="/workspaces", path_params=None, body=None, query=None,
           sub="user-1"):
    return {
        "httpMethod": method,
        "path": path,
        "resource": path,
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": query,
        "requestContext": {"authorizer": {"claims": {"sub": sub}}},
    }


@pytest.fixture(autouse=True)
def _disable_default_ws_helper(monkeypatch):
    """The api/conftest.py autouse patches resolve_workspace_id; the workspaces
    handler does not use it, so this is a no-op here, but we keep it for clarity.
    """
    yield


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_list_workspaces_returns_user_workspaces(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.list_workspaces.return_value = [
        {
            "PK": "USER#user-1#WORKSPACES",
            "SK": "WS#ws-abc",
            "user_id": "user-1",
            "workspace_id": "ws-abc",
            "name": "Default",
            "status": "active",
        }
    ]

    from backend.api.workspaces import handler
    res = handler(_event("GET"), None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["workspace_id"] == "ws-abc"
    # PK/SK stripped
    assert "PK" not in body["workspaces"][0]


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_create_workspace_returns_201_and_sets_active_when_first(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.create_workspace.return_value = {
        "PK": "USER#user-1#WORKSPACES",
        "SK": "WS#new-id",
        "workspace_id": "new-id",
        "name": "Default",
        "status": "active",
    }
    mock_db.get_active_workspace.return_value = None  # First workspace

    from backend.api.workspaces import handler
    res = handler(_event("POST", body={"name": "Default"}), None)
    assert res["statusCode"] == 201
    mock_db.create_workspace.assert_called_once()
    mock_db.set_active_workspace.assert_called_once()


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_create_workspace_does_not_overwrite_existing_active(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.create_workspace.return_value = {
        "workspace_id": "new-id", "name": "Second", "status": "active",
    }
    mock_db.get_active_workspace.return_value = "existing-id"

    from backend.api.workspaces import handler
    res = handler(_event("POST", body={"name": "Second"}), None)
    assert res["statusCode"] == 201
    mock_db.set_active_workspace.assert_not_called()


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_get_active_returns_active_workspace(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = "ws-1"
    mock_db.get_workspace.return_value = {"workspace_id": "ws-1", "name": "X", "status": "active"}

    from backend.api.workspaces import handler
    res = handler(_event("GET", path="/workspaces/active"), None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["active_workspace_id"] == "ws-1"


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_set_active_404_if_not_found(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_workspace.return_value = None

    from backend.api.workspaces import handler
    res = handler(
        _event("PUT", path="/workspaces/active", body={"workspace_id": "missing"}),
        None,
    )
    assert res["statusCode"] == 404


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_set_active_400_if_archived(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_workspace.return_value = {"workspace_id": "old", "status": "archived"}

    from backend.api.workspaces import handler
    res = handler(
        _event("PUT", path="/workspaces/active", body={"workspace_id": "old"}),
        None,
    )
    assert res["statusCode"] == 400


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_update_workspace_renames(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_workspace.return_value = {"workspace_id": "ws-1", "name": "Old"}

    from backend.api.workspaces import handler
    res = handler(
        _event("PUT", path="/workspaces/ws-1", path_params={"wid": "ws-1"},
               body={"name": "New"}),
        None,
    )
    assert res["statusCode"] == 200
    mock_db.update_workspace.assert_called_once()


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_archive_requires_confirm(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_workspace.return_value = {"workspace_id": "ws-1", "status": "active"}

    from backend.api.workspaces import handler
    res = handler(
        _event("DELETE", path="/workspaces/ws-1", path_params={"wid": "ws-1"},
               body={}),
        None,
    )
    assert res["statusCode"] == 400


@patch("backend.api.workspaces.boto3")
@patch("backend.api.workspaces.db")
def test_archive_with_confirm_succeeds(mock_db, mock_boto3):
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_workspace.return_value = {"workspace_id": "ws-1", "status": "active"}
    mock_db.get_active_workspace.return_value = "ws-1"
    mock_db.list_workspaces.return_value = [
        {"workspace_id": "ws-1", "status": "archived"},
        {"workspace_id": "ws-2", "status": "active"},
    ]

    from backend.api.workspaces import handler
    res = handler(
        _event("DELETE", path="/workspaces/ws-1", path_params={"wid": "ws-1"},
               body={"confirm": True}),
        None,
    )
    assert res["statusCode"] == 200
    mock_db.archive_workspace.assert_called_once()
    # Should fall over to ws-2 since ws-1 was active
    mock_db.set_active_workspace.assert_called_once_with(mock_table, "user-1", "ws-2")


def test_unauthorized_returns_401():
    from backend.api.workspaces import handler
    res = handler({"httpMethod": "GET", "requestContext": {}}, None)
    assert res["statusCode"] == 401

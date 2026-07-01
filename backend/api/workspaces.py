"""API handler for workspace CRUD.

Endpoints (all authenticated via Cognito):
  GET    /workspaces           — list user's workspaces
  POST   /workspaces           — create a new workspace
  GET    /workspaces/active    — get active workspace_id
  PUT    /workspaces/active    — set active workspace_id
  PUT    /workspaces/{wid}     — update name/description/status/paused_reason
  DELETE /workspaces/{wid}     — archive (soft delete) — requires {"confirm": true}

Workspace IDs are KSUIDs (URL-safe, lexically sortable). They are decoupled
from the human-readable workspace ``name``.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal

import boto3

from backend.shared import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        return super().default(o)


def _new_workspace_id() -> str:
    """Generate a fresh KSUID (URL-safe, lexically sortable)."""
    try:
        # Prefer the cyrusimapksuid package (provides ksuid.ksuid())
        import ksuid as ksuid_mod  # type: ignore

        if hasattr(ksuid_mod, "ksuid"):
            return str(ksuid_mod.ksuid())
        if hasattr(ksuid_mod, "Ksuid"):
            return str(ksuid_mod.Ksuid())
        if hasattr(ksuid_mod, "KsuidMs"):
            return str(ksuid_mod.KsuidMs())
    except Exception:
        pass

    # Fallback: time-prefixed urlsafe random — preserves lex sort
    import base64
    import os as _os
    import time as _time

    # 27-char ksuid-shape: 6 base32 chars from time + 21 base32 from randomness
    millis = int(_time.time() * 1000).to_bytes(8, "big")
    rnd = _os.urandom(16)
    raw = millis[-6:] + rnd
    return base64.b32encode(raw).decode("ascii").rstrip("=").lower()[:27]


def _get_user_id(event: dict) -> str:
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    )
    return claims.get("sub", "")


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _strip_internal_keys(item: dict) -> dict:
    return {
        k: v for k, v in item.items()
        if not k.startswith(("PK", "SK", "gsi"))
    }


def handler(event: dict, context) -> dict:
    """Lambda handler for /workspaces endpoints."""
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    method = (event.get("httpMethod") or "").upper()
    path = event.get("path") or event.get("resource") or ""
    path_params = event.get("pathParameters") or {}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    if method == "OPTIONS":
        return _response(200, {})

    # Active workspace endpoints
    if "/workspaces/active" in path:
        if method == "GET":
            return _get_active(table, user_id)
        if method == "PUT":
            return _set_active(table, user_id, event)
        return _response(405, {"error": "Method not allowed"})

    # Workspace-by-id endpoints
    wid = path_params.get("wid") or path_params.get("workspace_id") or ""
    if wid:
        if method == "PUT":
            return _update_workspace(table, user_id, wid, event)
        if method == "DELETE":
            return _archive_workspace(table, user_id, wid, event)
        if method == "GET":
            return _get_workspace(table, user_id, wid)
        return _response(405, {"error": "Method not allowed"})

    # Top-level /workspaces
    if method == "GET":
        return _list_workspaces(table, user_id)
    if method == "POST":
        return _create_workspace(table, user_id, event)

    return _response(405, {"error": "Method not allowed"})


def _list_workspaces(table, user_id: str) -> dict:
    items = db.list_workspaces(table, user_id)
    # Filter out archived workspaces from the switcher — they still exist in DDB
    # for audit but shouldn't appear in the UI.
    workspaces = [
        _strip_internal_keys(it)
        for it in items
        if it.get("status") != "archived"
    ]
    return _response(200, {"workspaces": workspaces})


def _create_workspace(table, user_id: str, event: dict) -> dict:
    body = json.loads(event.get("body") or "{}")
    name = (body.get("name") or "Default").strip()
    description = (body.get("description") or "").strip()

    workspace_id = _new_workspace_id()
    item = db.create_workspace(table, user_id, workspace_id, name, description)

    # If this is the user's first workspace, set it as active.
    existing_active = db.get_active_workspace(table, user_id)
    if not existing_active:
        db.set_active_workspace(table, user_id, workspace_id)

    return _response(201, {"workspace": _strip_internal_keys(item)})


def _get_workspace(table, user_id: str, workspace_id: str) -> dict:
    item = db.get_workspace(table, user_id, workspace_id)
    if not item:
        return _response(404, {"error": "Workspace not found"})
    return _response(200, {"workspace": _strip_internal_keys(item)})


def _update_workspace(table, user_id: str, workspace_id: str, event: dict) -> dict:
    body = json.loads(event.get("body") or "{}")
    allowed_fields = {"name", "description", "status", "paused_reason"}
    updates = {k: v for k, v in body.items() if k in allowed_fields}

    if "status" in updates and updates["status"] not in ("active", "paused", "archived"):
        return _response(400, {"error": "status must be active, paused, or archived"})

    if not updates:
        return _response(400, {"error": "No valid fields to update"})

    existing = db.get_workspace(table, user_id, workspace_id)
    if not existing:
        return _response(404, {"error": "Workspace not found"})

    db.update_workspace(table, user_id, workspace_id, **updates)
    item = db.get_workspace(table, user_id, workspace_id)
    return _response(200, {"workspace": _strip_internal_keys(item or existing)})


def _archive_workspace(table, user_id: str, workspace_id: str, event: dict) -> dict:
    body = json.loads(event.get("body") or "{}")
    if not body.get("confirm"):
        return _response(400, {"error": "Archive requires confirm=true"})

    existing = db.get_workspace(table, user_id, workspace_id)
    if not existing:
        return _response(404, {"error": "Workspace not found"})

    db.archive_workspace(table, user_id, workspace_id)

    # If we just archived the active workspace, clear / move the pointer.
    active = db.get_active_workspace(table, user_id)
    if active == workspace_id:
        # Pick another non-archived workspace, if any.
        all_ws = db.list_workspaces(table, user_id)
        next_active = next(
            (
                w.get("workspace_id")
                for w in all_ws
                if w.get("workspace_id") != workspace_id
                and w.get("status") != "archived"
            ),
            None,
        )
        if next_active:
            db.set_active_workspace(table, user_id, next_active)

    return _response(200, {"status": "archived", "workspace_id": workspace_id})


def _get_active(table, user_id: str) -> dict:
    workspace_id = db.get_active_workspace(table, user_id)
    if not workspace_id:
        return _response(200, {"active_workspace_id": None, "workspace": None})

    ws = db.get_workspace(table, user_id, workspace_id)
    return _response(200, {
        "active_workspace_id": workspace_id,
        "workspace": _strip_internal_keys(ws) if ws else None,
    })


def _set_active(table, user_id: str, event: dict) -> dict:
    body = json.loads(event.get("body") or "{}")
    workspace_id = (body.get("workspace_id") or "").strip()
    if not workspace_id:
        return _response(400, {"error": "workspace_id required"})

    ws = db.get_workspace(table, user_id, workspace_id)
    if not ws:
        return _response(404, {"error": "Workspace not found"})
    if ws.get("status") == "archived":
        return _response(400, {"error": "Cannot activate an archived workspace"})

    db.set_active_workspace(table, user_id, workspace_id)
    return _response(200, {
        "active_workspace_id": workspace_id,
        "workspace": _strip_internal_keys(ws),
    })

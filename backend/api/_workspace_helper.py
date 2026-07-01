"""Shared helpers for resolving the active workspace from an API request.

All workspace-scoped API handlers share the same resolution logic:
  1. If the request includes ``?workspace_id=<wid>``, use that (and verify it
     belongs to the caller).
  2. Otherwise, read the user's active workspace pointer from DDB.
  3. If neither is present, return None — the handler should respond 400.
"""

from __future__ import annotations

from typing import Optional

from backend.shared import db


def get_user_id(event: dict) -> str:
    """Extract Cognito user sub from API Gateway authorizer claims."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    )
    return claims.get("sub", "")


def resolve_workspace_id(table, event: dict, user_id: str) -> Optional[str]:
    """Return the workspace_id this request operates on, or None.

    Order of precedence:
      1. ?workspace_id=<wid> query param (if it belongs to the user)
      2. Active workspace pointer
    """
    qs = event.get("queryStringParameters") or {}
    override = (qs.get("workspace_id") or "").strip()
    if override:
        ws = db.get_workspace(table, user_id, override)
        if ws and ws.get("status") != "archived":
            return override
        # If the override is invalid, fall through to the active pointer.

    return db.get_active_workspace(table, user_id)

"""Shared data-access helpers for the offline eval harnesses.

Extracted from the eval scripts so the Tier 2 (learning-loop) and Tier 3
(full-pool relevance) harnesses — and any future scheduled eval job — read the
same way instead of each re-implementing user resolution, coercion, and
engagement grouping.
"""

from __future__ import annotations

import os
from collections import defaultdict

import boto3

from backend.shared import db

USER_POOL_ID = os.environ.get("USER_POOL_ID", "us-east-1_XXXXXXXXX")


def resolve_sub(user: str) -> str:
    """Accept a Cognito sub directly, or resolve an email to its sub."""
    if "@" not in user:
        return user
    cog = boto3.client("cognito-idp")
    resp = cog.list_users(UserPoolId=USER_POOL_ID, Filter=f'email = "{user}"', Limit=1)
    users = resp.get("Users", [])
    if not users:
        raise SystemExit(f"No Cognito user with email {user}")
    return users[0]["Username"]


def as_float(v, default: float = 0.0) -> float:
    """Best-effort float coercion (DDB Decimals, strings, None)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def engagement_by_paper(table, user_id: str, workspace_id: str) -> dict:
    """Group a workspace's engagement events by paper_id.

    Returns {paper_id: {"actions": [...], "active_ms": int, "rating": int|None}}.
    """
    by_paper: dict = defaultdict(lambda: {"actions": [], "active_ms": 0, "rating": None})
    for e in db.list_all_engagement_events(table, user_id, workspace_id):
        pid = e.get("paper_id", "")
        if not pid:
            continue
        rec = by_paper[pid]
        action = e.get("action", "")
        if action:
            rec["actions"].append(action)
        rec["active_ms"] = max(rec["active_ms"], int(as_float(e.get("active_ms"))))
        if e.get("rating") is not None:
            rec["rating"] = int(as_float(e.get("rating")))
    return by_paper

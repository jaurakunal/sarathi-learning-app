"""API handler: Brief Archive — paginated list of weekly briefs."""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db
from backend.api._workspace_helper import get_user_id as _get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        return super().default(o)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _parse_limit(qs: dict | None) -> int:
    if not qs:
        return DEFAULT_LIMIT
    raw = qs.get("limit")
    if raw is None:
        return DEFAULT_LIMIT
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if n <= 0:
        return DEFAULT_LIMIT
    return min(n, MAX_LIMIT)


def handler(event: dict, context) -> dict:
    """GET /briefs — paginated weekly briefs for the authenticated user.

    Query params:
      - limit: page size (1..100, default 20)
      - after_week: ISO date (YYYY-MM-DD) — return briefs strictly older than this week

    Sorts newest-first by week (descending). Returns:
      {"briefs": [{week, content, generated_at}], "next_after_week": "<iso>" | null}
    """
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    qs = event.get("queryStringParameters") or {}
    limit = _parse_limit(qs)
    after_week = (qs or {}).get("after_week")

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    # Briefs are stored as PK=USER#<sub>#WS#<wid>#BRIEF, SK=WEEK#<iso>.
    # ScanIndexForward=False yields newest first.
    key_cond = Key("PK").eq(db._brief_pk(user_id, workspace_id))
    if after_week:
        # Return weeks strictly less than after_week (older).
        key_cond = key_cond & Key("SK").lt(f"WEEK#{after_week}")

    resp = table.query(
        KeyConditionExpression=key_cond,
        ScanIndexForward=False,
        Limit=limit,
    )
    items = resp.get("Items", [])

    briefs = []
    for item in items:
        week = item.get("week") or item.get("SK", "").replace("WEEK#", "")
        briefs.append({
            "week": week,
            "content": item.get("content", ""),
            "generated_at": item.get("created_at", ""),
        })

    # next_after_week: cursor for next page. Use the oldest week we returned, so the
    # next call returns weeks strictly older than that. Only set if DDB indicates
    # there are more items in the partition.
    next_after_week = None
    if briefs and resp.get("LastEvaluatedKey"):
        next_after_week = briefs[-1]["week"]

    return _response(200, {
        "briefs": briefs,
        "next_after_week": next_after_week,
    })

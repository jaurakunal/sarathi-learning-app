"""API handler: Profile + progress reads."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        return super().default(o)


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
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _strip_ddb_keys(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith(("PK", "SK", "gsi")) and k != "user_id"}


def handler(event: dict, context) -> dict:
    """Lambda handler for profile API.

    GET /profile — full profile + history + engagement stats
    """
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    # 1. Full profile
    profile = db.get_full_profile(table, user_id)

    # 2. Profile history (frontier timeline)
    history_resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}#PROFILE_HISTORY"),
        ScanIndexForward=False,
        Limit=20,
    )
    history = history_resp.get("Items", [])

    # 3. Engagement stats for the last 7 days
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = db.list_engagement_events(table, user_id, since, now)

    # Aggregate stats
    stats = {
        "papers_read": 0,
        "papers_dismissed": 0,
        "papers_bookmarked": 0,
        "questions_asked": 0,
        "source_clicks": 0,
        "sections_expanded": 0,
        "total_active_ms": 0,
    }
    for e in events:
        action = e.get("action", "")
        if action == "read":
            stats["papers_read"] += 1
            if e.get("active_ms"):
                stats["total_active_ms"] += int(e["active_ms"])
        elif action == "dismiss":
            stats["papers_dismissed"] += 1
        elif action == "bookmark":
            stats["papers_bookmarked"] += 1
        elif action == "ask":
            stats["questions_asked"] += 1
        elif action == "source_click":
            stats["source_clicks"] += 1
        elif action == "expand":
            stats["sections_expanded"] += 1

    # 4. Build response
    areas = []
    for area in profile.get("areas", []):
        areas.append({
            "id": area.get("id", ""),
            "name": area.get("name", area.get("id", "")),
            "status": area.get("status", "active"),
            "frontier": area.get("frontier", ""),
            "last_engaged": area.get("last_engaged"),
        })

    hypothesis = None
    if profile.get("hypothesis"):
        h = profile["hypothesis"]
        hypothesis = {
            "statement": h.get("statement", ""),
            "supporting": h.get("supporting", []),
            "refuting": h.get("refuting", []),
            "refining": h.get("refining", []),
        }

    summaries = {}
    for s in profile.get("summaries", []):
        tier = s.get("tier", "")
        content = s.get("content", "")
        if content and content != "No activity yet.":
            summaries[tier] = content

    timeline = []
    for h in history:
        entry = {
            "ts": h.get("ts", h.get("SK", "").replace("TS#", "")),
            "type": h.get("type", ""),
            "changelog": h.get("changelog", ""),
            "changes": h.get("changes", []),
        }
        if h.get("frontier_snapshots"):
            entry["frontier_snapshots"] = h["frontier_snapshots"]
        if h.get("hypothesis_evidence_added"):
            entry["hypothesis_evidence_added"] = h["hypothesis_evidence_added"]
        timeline.append(entry)

    return _response(200, {
        "areas": areas,
        "hypothesis": hypothesis,
        "summaries": summaries,
        "stats_7d": stats,
        "timeline": timeline,
        "learning_style": profile.get("meta", {}).get("learning_style"),
    })

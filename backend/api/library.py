"""API handler: Library view — all engaged papers with engagement depth."""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db
from backend.api._workspace_helper import get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


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


def _compute_engagement_score(actions: dict) -> int:
    """Compute a 0-100 engagement depth score from actions."""
    score = 0
    if actions.get("read"):
        score += 20
    if actions.get("ask"):
        score += 30
    if actions.get("source_click"):
        score += 15
    if actions.get("bookmark"):
        score += 10
    if actions.get("rated_up"):
        score += 10
    if actions.get("expand_count", 0) > 2:
        score += 10
    if actions.get("view_count", 0) > 1:
        score += 5
    return min(score, 100)


def handler(event: dict, context) -> dict:
    """Lambda handler for library API.

    GET /library — all papers the user has engaged with in the active workspace,
    sorted by depth.
    """
    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    # 1. Get all engagement events for this workspace
    engagement_pk = db._engagement_pk(user_id, workspace_id)
    resp = table.query(KeyConditionExpression=Key("PK").eq(engagement_pk))
    events = resp.get("Items", [])
    while resp.get("LastEvaluatedKey"):
        resp = table.query(
            KeyConditionExpression=Key("PK").eq(engagement_pk),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        events.extend(resp.get("Items", []))

    # 2. Aggregate by paper_id
    paper_actions: dict[str, dict] = defaultdict(lambda: {
        "read": False,
        "ask": False,
        "source_click": False,
        "bookmark": False,
        "rated_up": False,
        "rated_down": False,
        "expand_count": 0,
        "view_count": 0,
        "total_active_ms": 0,
        "first_engaged": None,
        "last_engaged": None,
    })

    for e in events:
        paper_id = e.get("paper_id", "")
        if not paper_id:
            continue
        action = e.get("action", "")
        ts = e.get("ts", "")
        actions = paper_actions[paper_id]

        if action == "read":
            actions["read"] = True
            if e.get("active_ms"):
                actions["total_active_ms"] += int(e["active_ms"])
        elif action == "ask":
            actions["ask"] = True
        elif action == "source_click":
            actions["source_click"] = True
        elif action == "bookmark":
            actions["bookmark"] = True
        elif action == "rate":
            rating = int(e.get("rating", 0))
            if rating >= 4:
                actions["rated_up"] = True
            elif 0 < rating <= 2:
                actions["rated_down"] = True
        elif action == "expand":
            actions["expand_count"] += 1
        elif action == "view":
            actions["view_count"] += 1

        if ts:
            if not actions["first_engaged"] or ts < actions["first_engaged"]:
                actions["first_engaged"] = ts
            if not actions["last_engaged"] or ts > actions["last_engaged"]:
                actions["last_engaged"] = ts

    # 3. Get feed cards to enrich with title/hook
    feed_pk = db._feed_pk(user_id, workspace_id)
    cards_resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(feed_pk) & Key("SK").begins_with("CARD#")
        ),
    )
    cards = cards_resp.get("Items", [])

    card_by_paper: dict[str, dict] = {}
    for card in cards:
        pid = card.get("paper_id", "")
        if card.get("card_type", "new_paper") not in ("new_paper", ""):
            continue  # derived cards (connect, ...) reuse a paper_id
        if pid and pid not in card_by_paper:
            card_by_paper[pid] = card

    # 4. Get conversation turn counts (workspace-scoped)
    conv_resp = table.query(
        IndexName="GSI1",
        KeyConditionExpression=(
            Key("gsi1pk").eq(db._gsi_user_scope(user_id, workspace_id))
            & Key("gsi1sk").begins_with("CONV#")
        ),
    )
    conv_items = conv_resp.get("Items", [])
    conv_turns: dict[str, int] = {}
    for c in conv_items:
        conv_id = c.get("conv_id", "")
        turn_count = int(c.get("turn_count", 0))
        if conv_id and turn_count:
            conv_turns[conv_id] = turn_count

    # 5. Build library entries
    library = []
    for paper_id, actions in paper_actions.items():
        card = card_by_paper.get(paper_id, {})
        score = _compute_engagement_score(actions)

        if not actions["read"] and actions["view_count"] == 0 and not actions["ask"]:
            continue

        entry = {
            "paper_id": paper_id,
            "title": card.get("hook", paper_id),
            "card_id": card.get("card_id"),
            "source_url": card.get("source_url", ""),
            "engagement_score": score,
            "actions": {
                "read": actions["read"],
                "asked": actions["ask"],
                "bookmarked": actions["bookmark"],
                "rated_up": actions["rated_up"],
                "source_clicked": actions["source_click"],
            },
            "question_count": conv_turns.get(paper_id, 0),
            "total_active_ms": actions["total_active_ms"],
            "first_engaged": actions["first_engaged"],
            "last_engaged": actions["last_engaged"],
        }
        library.append(entry)

    library.sort(key=lambda x: x["engagement_score"], reverse=True)

    return _response(200, {
        "workspace_id": workspace_id,
        "papers": library,
        "total": len(library),
    })

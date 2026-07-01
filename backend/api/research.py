"""API handler for the research scaffold view."""

from __future__ import annotations

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db
from backend.api._workspace_helper import get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


def handler(event: dict, context) -> dict:
    """GET /research — returns structured research data grouped by tags."""
    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    feed_pk = db._feed_pk(user_id, workspace_id)

    # 1. Get all feed cards
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(feed_pk) & Key("SK").begins_with("CARD#")
        ),
    )
    cards = resp.get("Items", [])

    # 2. Separate into core (tagged) vs untagged-but-engaged
    core_cards = [c for c in cards if c.get("relevance") == "core"]
    untagged = [
        c for c in cards
        if not c.get("relevance")
        and (c.get("bookmarked") or (c.get("rating") and int(c.get("rating", 0)) >= 4))
    ]

    # 3. Group core cards by tag
    tag_groups: dict[str, list] = {}
    for card in core_cards:
        card_tags = card.get("tags", [])
        if not card_tags:
            card_tags = ["untagged"]
        for tag in card_tags:
            if tag not in tag_groups:
                tag_groups[tag] = []
            tag_groups[tag].append(_card_summary(card))

    # 4. Get all pinned turns across conversations (workspace-scoped)
    pinned_by_paper: dict[str, list] = {}
    conv_resp = table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("gsi1pk").eq(
            db._gsi_user_scope(user_id, workspace_id)
        ),
    )
    convs = conv_resp.get("Items", [])

    for conv in convs:
        conv_id = conv.get("conv_id", "")
        turns_resp = table.query(
            KeyConditionExpression=(
                Key("PK").eq(db._conv_pk(user_id, workspace_id, conv_id))
                & Key("SK").begins_with("TURN#")
            ),
            FilterExpression="pinned = :t",
            ExpressionAttributeValues={":t": True},
        )
        for turn in turns_resp.get("Items", []):
            if conv_id not in pinned_by_paper:
                pinned_by_paper[conv_id] = []
            pinned_by_paper[conv_id].append({
                "seq": int(turn.get("seq", 0)),
                "request": turn.get("request", ""),
                "response": (turn.get("response") or "")[:500],
                "pin_note": turn.get("pin_note", ""),
                "pinned_at": turn.get("pinned_at", ""),
            })

    # 5. Build response
    response = {
        "workspace_id": workspace_id,
        "tag_groups": tag_groups,
        "untagged_engaged": [_card_summary(c) for c in untagged],
        "pinned_insights": pinned_by_paper,
        "stats": {
            "core_papers": len(core_cards),
            "total_tags": len(tag_groups),
            "pinned_insights": sum(len(v) for v in pinned_by_paper.values()),
            "untagged_engaged": len(untagged),
        },
    }

    return _response(200, response)


def _card_summary(card: dict) -> dict:
    return {
        "card_id": card.get("card_id", ""),
        "paper_id": card.get("paper_id", ""),
        "hook": card.get("hook", ""),
        "tags": card.get("tags", []),
        "source_url": card.get("source_url", ""),
    }


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
        },
        "body": json.dumps(body, default=str),
    }

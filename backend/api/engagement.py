"""API handler: Log engagement events."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from backend.shared import db
from backend.api._workspace_helper import get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")

VALID_ACTIONS = {"view", "expand", "read", "dismiss", "restore", "bookmark", "ask", "rate", "impression", "source_click", "tag", "pin", "unpin"}


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def handler(event: dict, context) -> dict:
    """Lambda handler for engagement logging.

    POST /engagement — log a user action (view, expand, read, dismiss, etc.)
    """
    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Invalid JSON body"})

    paper_id = body.get("paper_id")
    card_id = body.get("card_id")
    action = body.get("action")

    if not action:
        return _response(400, {"error": "action is required"})
    if not paper_id and not card_id:
        return _response(400, {"error": "paper_id or card_id is required"})

    if action not in VALID_ACTIONS:
        return _response(400, {"error": f"Invalid action. Must be one of: {sorted(VALID_ACTIONS)}"})

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    engagement_event = {
        "ts": ts,
        "paper_id": paper_id,
        "card_id": card_id or "",
        "action": action,
    }

    if body.get("active_ms") is not None:
        engagement_event["active_ms"] = int(body["active_ms"])
    if body.get("scroll_depth_pct") is not None:
        engagement_event["scroll_depth_pct"] = int(body["scroll_depth_pct"])
    if body.get("section"):
        engagement_event["section"] = str(body["section"])
    if body.get("interactions") is not None:
        engagement_event["interactions"] = int(body["interactions"])
    if body.get("rating") is not None:
        engagement_event["rating"] = int(body["rating"])

    db.put_engagement_event(table, user_id, workspace_id, engagement_event)

    if action == "view" and card_id:
        try:
            table.update_item(
                Key={
                    "PK": db._feed_pk(user_id, workspace_id),
                    "SK": f"CARD#{card_id}",
                },
                UpdateExpression="ADD view_count :one",
                ExpressionAttributeValues={":one": 1},
            )
        except Exception:
            pass
    elif action == "dismiss" and card_id:
        db.update_feed_card_meta(
            table, user_id, workspace_id, card_id, {"dismissed": True}
        )
    elif action == "restore" and card_id:
        db.update_feed_card_meta(
            table, user_id, workspace_id, card_id, {"dismissed": False}
        )
    elif action == "bookmark" and card_id:
        is_bookmarked = body.get("section") != "remove"
        db.update_feed_card_meta(
            table, user_id, workspace_id, card_id, {"bookmarked": is_bookmarked}
        )
    elif action == "rate" and card_id and body.get("rating") is not None:
        rating_val = int(body["rating"])
        db.update_feed_card_meta(
            table, user_id, workspace_id, card_id, {"rating": rating_val}
        )
    elif action == "tag" and card_id:
        relevance = body.get("relevance", "core")
        tags = body.get("tags", [])
        db.tag_paper(table, user_id, workspace_id, card_id, relevance, tags)
    elif action == "pin" and paper_id:
        conv_id = paper_id
        seq = int(body.get("seq", 0))
        pin_note = body.get("pin_note", "")
        if seq > 0:
            db.pin_turn(table, user_id, workspace_id, conv_id, seq, pin_note)
    elif action == "unpin" and paper_id:
        conv_id = paper_id
        seq = int(body.get("seq", 0))
        if seq > 0:
            db.unpin_turn(table, user_id, workspace_id, conv_id, seq)

    logger.info("Engagement logged: user=%s ws=%s action=%s paper=%s",
                user_id, workspace_id, action, paper_id)

    return _response(201, {"status": "ok", "ts": ts})

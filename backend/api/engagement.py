"""API handler: Log engagement events."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from backend.shared import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")

VALID_ACTIONS = {"view", "expand", "read", "dismiss", "bookmark", "ask"}


def _get_user_id(event: dict) -> str:
    """Extract Cognito user sub from API Gateway authorizer claims."""
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
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def handler(event: dict, context) -> dict:
    """Lambda handler for engagement logging.

    POST /engagement — log a user action (view, expand, read, dismiss, etc.)
    """
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Invalid JSON body"})

    # Validate required fields
    paper_id = body.get("paper_id")
    card_id = body.get("card_id")
    action = body.get("action")

    if not paper_id or not action:
        return _response(400, {"error": "paper_id and action are required"})

    if action not in VALID_ACTIONS:
        return _response(400, {"error": f"Invalid action. Must be one of: {sorted(VALID_ACTIONS)}"})

    # Build engagement event
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    engagement_event = {
        "ts": ts,
        "paper_id": paper_id,
        "card_id": card_id or "",
        "action": action,
    }

    # Optional numeric fields
    if body.get("active_ms") is not None:
        engagement_event["active_ms"] = int(body["active_ms"])
    if body.get("scroll_depth_pct") is not None:
        engagement_event["scroll_depth_pct"] = int(body["scroll_depth_pct"])
    if body.get("interactions") is not None:
        engagement_event["interactions"] = int(body["interactions"])

    # Write to DDB
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)
    db.put_engagement_event(table, user_id, engagement_event)

    logger.info("Engagement logged: user=%s action=%s paper=%s", user_id, action, paper_id)

    return _response(201, {"status": "ok", "ts": ts})

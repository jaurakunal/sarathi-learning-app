"""API handler: Feed reads (paginated card listing + single card)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

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


def _touch_last_active(table, user_id: str, workspace_id: str) -> None:
    """Update last_active_at on the user's SYSTEM#USERS record + the workspace,
    and record the user as active today (append-only, for DAU/WAU/MAU)."""
    try:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        table.update_item(
            Key={"PK": "SYSTEM#USERS", "SK": f"USER#{user_id}"},
            UpdateExpression="SET last_active_at = :ts",
            ExpressionAttributeValues={":ts": now},
        )
        if workspace_id:
            db.update_workspace(table, user_id, workspace_id, last_active_at=now)
        # Opening the feed is the canonical "active user" signal.
        db.record_daily_activity(table, user_id, now_dt.strftime("%Y-%m-%d"))
    except Exception:
        pass


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


def _strip_internal_keys(card: dict) -> dict:
    """Remove DDB internal keys (PK, SK, gsi*) from the response."""
    return {
        k: v for k, v in card.items()
        if not k.startswith(("PK", "SK", "gsi")) and k != "user_id"
    }


def handler(event: dict, context) -> dict:
    """Lambda handler for feed API.

    GET /feed — paginated feed cards, newest first
    GET /feed/{card_id} — single card detail
    """
    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    _touch_last_active(table, user_id, workspace_id)

    path_params = event.get("pathParameters") or {}
    card_id = path_params.get("card_id")

    if card_id:
        return _get_single_card(table, user_id, workspace_id, card_id)
    else:
        return _list_feed(table, user_id, workspace_id, event)


def _get_single_card(table, user_id: str, workspace_id: str, card_id: str) -> dict:
    """GET /feed/{card_id} — full card detail."""
    card = db.get_feed_card(table, user_id, workspace_id, card_id)
    if not card:
        return _response(404, {"error": "Card not found"})

    return _response(200, _strip_internal_keys(card))


def _list_feed(table, user_id: str, workspace_id: str, event: dict) -> dict:
    """GET /feed — paginated card listing, newest first."""
    query_params = event.get("queryStringParameters") or {}
    limit = min(int(query_params.get("limit", "20")), 50)
    last_key_raw = query_params.get("lastKey")

    last_key = None
    if last_key_raw:
        try:
            last_key = json.loads(last_key_raw)
        except (json.JSONDecodeError, TypeError):
            return _response(400, {"error": "Invalid lastKey parameter"})

    cards, next_key = db.list_feed_cards(
        table, user_id, workspace_id, limit=limit, last_key=last_key
    )

    show_dismissed = query_params.get("show_dismissed") == "true"
    if not show_dismissed:
        cards = [c for c in cards if not c.get("dismissed")]

    read_paper_ids = db.get_read_paper_ids(table, user_id, workspace_id)

    response_cards = []
    for card in cards:
        response_cards.append({
            "card_id": card.get("card_id", ""),
            "paper_id": card.get("paper_id", ""),
            "hook": card.get("hook", ""),
            "why_you_now": card.get("why_you_now", ""),
            "time_estimate": card.get("time_estimate", ""),
            "card_type": card.get("card_type", ""),
            "created_at": card.get("created_at", ""),
            "read": card.get("paper_id", "") in read_paper_ids,
            "bookmarked": bool(card.get("bookmarked", False)),
            "rating": int(card["rating"]) if card.get("rating") and int(card.get("rating", 0)) != 0 else None,
            "view_count": int(card.get("view_count", 0)),
            "dismissed": bool(card.get("dismissed", False)),
        })

    body = {"cards": response_cards, "lastKey": next_key, "workspace_id": workspace_id}
    return _response(200, body)

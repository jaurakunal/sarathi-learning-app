"""API handler: Feed reads (paginated card listing + single card)."""

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
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    path_params = event.get("pathParameters") or {}
    card_id = path_params.get("card_id")

    if card_id:
        return _get_single_card(table, user_id, card_id)
    else:
        return _list_feed(table, user_id, event)


def _get_single_card(table, user_id: str, card_id: str) -> dict:
    """GET /feed/{card_id} — full card detail."""
    card = db.get_feed_card(table, user_id, card_id)
    if not card:
        return _response(404, {"error": "Card not found"})

    return _response(200, _strip_internal_keys(card))


def _list_feed(table, user_id: str, event: dict) -> dict:
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

    cards, next_key = db.list_feed_cards(table, user_id, limit=limit, last_key=last_key)

    # Get set of read paper IDs for marking cards
    read_paper_ids = db.get_read_paper_ids(table, user_id)

    # Return compact card summaries for the list view
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
            "bookmarked": card.get("bookmarked", False),
            "rating": card.get("rating"),
        })

    body = {"cards": response_cards, "lastKey": next_key}
    return _response(200, body)

"""Feed-freshness synthetic canary.

Runs on a schedule an hour after the nightly pipeline should have finished.
Counts feed cards created in the last 24 hours across all active (non-paused)
workspaces and emits metrics that let us alarm on a stale feed DIRECTLY —
without trusting any pipeline step to report honestly.

This is the guard against the app's signature failure: a nightly pipeline that
reports SUCCEEDED but produced zero feed cards (Bedrock outage in triage, zero
new candidates in discover, an auto-paused workspace, etc.). None of those show
up as a failed execution; only counting the actual output catches them.

Emits (namespace Sarathi):
  - ActiveWorkspaces         : number of non-paused workspaces expecting cards
  - FeedCardsLast24h         : total cards created in the last 24h
  - FeedFreshnessBreach      : 1 if there are active workspaces but zero fresh
                               cards, else 0. This is the metric to alarm on.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db, metrics

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
LOOKBACK_HOURS = int(os.environ.get("FRESHNESS_LOOKBACK_HOURS", "24"))


def _active_users(table) -> list[str]:
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq("SYSTEM#USERS") & Key("SK").begins_with("USER#")
        ),
    )
    return [
        u.get("user_id", "")
        for u in resp.get("Items", [])
        if u.get("status") == "active" and u.get("user_id")
    ]


def _count_fresh_cards(table, user_id: str, workspace_id: str, cutoff_iso: str) -> int:
    """Count feed cards in this workspace with created_at >= cutoff."""
    pk = db._feed_pk(user_id, workspace_id)
    count = 0
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("CARD#"),
        ProjectionExpression="created_at",
    )
    items = resp.get("Items", [])
    while resp.get("LastEvaluatedKey"):
        resp = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("CARD#"),
            ProjectionExpression="created_at",
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    for it in items:
        if (it.get("created_at") or "") >= cutoff_iso:
            count += 1
    return count


def handler(event: dict, context) -> dict:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    active_workspaces = 0
    total_cards = 0
    per_ws: list[dict] = []

    for user_id in _active_users(table):
        for ws in db.list_workspaces(table, user_id):
            wid = ws.get("workspace_id", "")
            if not wid or ws.get("status") != "active":
                continue
            active_workspaces += 1
            n = _count_fresh_cards(table, user_id, wid, cutoff_iso)
            total_cards += n
            per_ws.append({"user_id": user_id, "workspace_id": wid, "cards": n})

    breach = 1 if (active_workspaces > 0 and total_cards == 0) else 0

    metrics.emit("ActiveWorkspaces", active_workspaces)
    metrics.emit("FeedCardsLast24h", total_cards)
    metrics.emit("FeedFreshnessBreach", breach)

    result = {
        "active_workspaces": active_workspaces,
        "feed_cards_last_24h": total_cards,
        "freshness_breach": breach,
        "cutoff": cutoff_iso,
        "per_workspace": per_ws,
    }
    if breach:
        logger.error("FEED FRESHNESS BREACH: %s", result)
    else:
        logger.info("Freshness canary: %s", result)
    return result

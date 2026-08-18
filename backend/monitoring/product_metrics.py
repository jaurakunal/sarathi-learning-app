"""Daily product-metrics aggregator.

Runs once a day (~06:00 UTC) for the previous full day. Computes the metrics a
PM cares about — acquisition, activation funnel, DAU/WAU/MAU, engagement depth,
retention, and area-of-interest distribution — and writes a snapshot to
SYSTEM#METRICS / DATE#<day>. The weekly digest reads these snapshots; storing
each day's active-user id set lets WAU/MAU/retention be computed as unions of
recent snapshots with no re-scan.

Cognito is the acquisition spine: SYSTEM#USERS only exists after a user finishes
workspace onboarding, so counting signups (including people who dropped off
mid-onboarding) requires listing the user pool.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")

_ENGAGEMENT_BUCKETS = {
    "read": "reads", "read_fully": "reads", "read_full": "reads",
    "dismiss": "dismisses",
    "bookmark": "bookmarks", "save": "bookmarks",
    "source_click": "source_clicks", "click_source": "source_clicks",
    "pin": "pins",
}


def _list_cognito_users(pool_id: str) -> list[dict]:
    """Return [{sub, created, provider}] for every user in the pool."""
    if not pool_id:
        return []
    client = boto3.client("cognito-idp")
    users: list[dict] = []
    kwargs = {"UserPoolId": pool_id, "Limit": 60}
    while True:
        resp = client.list_users(**kwargs)
        for u in resp.get("Users", []):
            attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
            provider = "cognito"
            if "OidcSSO" in (u.get("Username") or "") or "identities" in attrs:
                provider = "oidc"
            users.append({
                "sub": attrs.get("sub", u.get("Username", "")),
                "created": u.get("UserCreateDate"),
                "provider": provider,
            })
        token = resp.get("PaginationToken")
        if not token:
            break
        kwargs["PaginationToken"] = token
    return users


def _classify_funnel(table, users: list[dict]) -> dict:
    """Place each signed-up user in the activation funnel."""
    signed_up = len(users)
    user_meta = 0
    completed = 0
    for u in users:
        sub = u["sub"]
        if not sub:
            continue
        if db.get_user_meta(table, sub):
            user_meta += 1
        # Completed workspace onboarding => a SYSTEM#USERS registry record.
        reg = table.get_item(Key={"PK": "SYSTEM#USERS", "SK": f"USER#{sub}"}).get("Item")
        if reg:
            completed += 1
    return {"signed_up": signed_up, "user_meta": user_meta, "completed": completed}


def _rolling_active(table, day: str, active_today: set) -> tuple[int, int]:
    """WAU/MAU = distinct union of active-user id sets over the last 7 / 30 days.

    Reads prior snapshots' stored active_user_ids and unions with today's.
    """
    since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
    snaps = db.list_metrics_snapshots(table, since)
    by_day = {s.get("day"): set(s.get("active_user_ids", []) or []) for s in snaps}
    by_day[day] = set(active_today)

    def union_last(n: int) -> set:
        acc: set = set()
        for i in range(n):
            d = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
            acc |= by_day.get(d, set())
        return acc

    return len(union_last(7)), len(union_last(30))


def _engagement_depth(table, active_ids: list[str], day: str) -> dict:
    """Aggregate engagement events + chat turns for the active users that day.

    Bounded by the active-user set (small), so this only touches users who
    actually did something that day.
    """
    depth = {"reads": 0, "dismisses": 0, "bookmarks": 0, "source_clicks": 0,
             "pins": 0, "chat_messages": 0, "active_ms": 0}
    lo, hi = f"TS#{day}T00:00:00", f"TS#{day}T23:59:59.999Z"
    for sub in active_ids:
        for ws in db.list_workspaces(table, sub):
            wid = ws.get("workspace_id", "")
            if not wid:
                continue
            # Engagement events in the day window.
            resp = table.query(
                KeyConditionExpression=(
                    Key("PK").eq(db._engagement_pk(sub, wid)) & Key("SK").between(lo, hi)
                ),
            )
            for e in resp.get("Items", []):
                action = (e.get("action") or "").lower()
                bucket = _ENGAGEMENT_BUCKETS.get(action)
                if bucket:
                    depth[bucket] += 1
                try:
                    depth["active_ms"] += int(e.get("active_ms", 0) or 0)
                except (TypeError, ValueError):
                    pass
            # Chat turns created that day (across this workspace's conversations).
            for conv in db.list_all_conversations(table, sub, wid):
                cid = conv.get("conv_id") or conv.get("SK", "").replace("CONV#", "")
                if not cid:
                    continue
                for t in db.get_conversation_turns(table, sub, wid, cid):
                    if (t.get("request_ts") or "") [:10] == day and (t.get("request") or "").strip():
                        depth["chat_messages"] += 1
    return depth


def _area_distribution(table, users: list[dict]) -> dict:
    """Tally area-of-interest labels across all users' active workspaces."""
    counts: dict[str, int] = {}
    for u in users:
        sub = u["sub"]
        if not sub:
            continue
        for ws in db.list_workspaces(table, sub):
            wid = ws.get("workspace_id", "")
            if not wid or ws.get("status") == "archived":
                continue
            for area in db.get_profile_areas(table, sub, wid):
                label = (area.get("label") or area.get("name") or area.get("id") or "").strip()
                if label:
                    counts[label] = counts.get(label, 0) + 1
    return counts


def _workspace_stats(table, users: list[dict]) -> dict:
    stats = {"active": 0, "paused": 0, "archived": 0}
    for u in users:
        sub = u["sub"]
        if not sub:
            continue
        for ws in db.list_workspaces(table, sub):
            status = ws.get("status", "active")
            stats[status] = stats.get(status, 0) + 1
    return stats


def handler(event: dict, context) -> dict:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    # Default to yesterday (the previous full UTC day).
    day = (event or {}).get("day")
    if not day:
        day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    users = _list_cognito_users(USER_POOL_ID)
    new_signups = sum(
        1 for u in users
        if u["created"] and u["created"].astimezone(timezone.utc).strftime("%Y-%m-%d") == day
    )

    active_ids = db.list_daily_active_user_ids(table, day)
    wau, mau = _rolling_active(table, day, set(active_ids))

    snapshot = {
        "total_users": len(users),
        "new_signups": new_signups,
        "funnel": _classify_funnel(table, users),
        "dau": len(active_ids),
        "wau": wau,
        "mau": mau,
        "active_user_ids": active_ids,
        "engagement": _engagement_depth(table, active_ids, day),
        "areas": _area_distribution(table, users),
        "workspaces": _workspace_stats(table, users),
    }
    db.put_metrics_snapshot(table, day, snapshot)
    logger.info("Product metrics for %s: signups=%d dau=%d wau=%d mau=%d funnel=%s",
                day, new_signups, snapshot["dau"], wau, mau, snapshot["funnel"])
    # Don't echo the full active-user id list in the return.
    return {k: v for k, v in snapshot.items() if k != "active_user_ids"} | {"day": day}

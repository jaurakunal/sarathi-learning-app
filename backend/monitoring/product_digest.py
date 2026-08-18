"""Weekly product-metrics digest -> Slack.

Runs Monday morning, reads the daily snapshots written by product_metrics, and
posts a readable summary to the same Slack channel the alarms use. It publishes
to the alarm SNS topic in AWS Chatbot's "custom notification" schema, so it
reuses the existing SNS -> Chatbot -> Slack wiring (no separate webhook).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

from backend.shared import db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
ALARM_TOPIC_ARN = os.environ.get("ALARM_TOPIC_ARN", "")


def _latest_snapshot_on_or_before(table, day: str) -> dict | None:
    """The most recent snapshot at or before `day` (within a 10-day lookback)."""
    since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
    snaps = db.list_metrics_snapshots(table, since)
    snaps = [s for s in snaps if s.get("day", "") <= day]
    return snaps[-1] if snaps else None


def _sum_new_signups(table, end_day: str, days: int) -> int:
    since = (datetime.strptime(end_day, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    snaps = db.list_metrics_snapshots(table, since)
    return sum(int(s.get("new_signups", 0) or 0) for s in snaps if s.get("day", "") <= end_day)


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _delta(cur: int, prev: int) -> str:
    d = cur - prev
    if d > 0:
        return f"(+{d})"
    if d < 0:
        return f"({d})"
    return "(no change)"


def _build_description(table, day: str) -> str:
    cur = _latest_snapshot_on_or_before(table, day)
    if not cur:
        return "No metrics snapshot available yet. The daily aggregator may not have run."

    prev_day = (datetime.strptime(cur["day"], "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    prev = _latest_snapshot_on_or_before(table, prev_day)

    dau, wau, mau = _int(cur.get("dau")), _int(cur.get("wau")), _int(cur.get("mau"))
    total_users = _int(cur.get("total_users"))
    signups_7d = _sum_new_signups(table, cur["day"], 7)
    funnel = cur.get("funnel", {}) or {}
    eng = cur.get("engagement", {}) or {}
    stickiness = f"{(dau / mau * 100):.0f}%" if mau else "n/a"

    lines = [
        f"*Users:* {total_users} total · {signups_7d} new this week",
    ]
    if prev:
        lines.append(
            f"*Active:* DAU {dau} · WAU {wau} {_delta(wau, _int(prev.get('wau')))} · "
            f"MAU {mau} {_delta(mau, _int(prev.get('mau')))} · stickiness {stickiness}"
        )
    else:
        lines.append(f"*Active:* DAU {dau} · WAU {wau} · MAU {mau} · stickiness {stickiness}")

    su = _int(funnel.get("signed_up"))
    um = _int(funnel.get("user_meta"))
    comp = _int(funnel.get("completed"))
    conv_um = f"{(um / su * 100):.0f}%" if su else "n/a"
    conv_comp = f"{(comp / su * 100):.0f}%" if su else "n/a"
    lines.append(
        f"*Onboarding funnel:* {su} signed up → {um} set a profile ({conv_um}) → "
        f"{comp} completed a workspace ({conv_comp})"
    )

    lines.append(
        f"*Engagement (this week's active users):* {_int(eng.get('reads'))} reads · "
        f"{_int(eng.get('bookmarks'))} bookmarks · {_int(eng.get('dismisses'))} dismisses · "
        f"{_int(eng.get('chat_messages'))} chat messages"
    )

    areas = cur.get("areas", {}) or {}
    if areas:
        top = sorted(areas.items(), key=lambda kv: -_int(kv[1]))[:5]
        lines.append("*Top areas of interest:* " + ", ".join(f"{k} ({_int(v)})" for k, v in top))

    return "\n".join(lines)


def handler(event: dict, context) -> dict:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    day = (event or {}).get("day") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    description = _build_description(table, day)

    payload = {
        "version": "1.0",
        "source": "custom",
        "content": {
            "title": f"📊 Sārathi weekly product metrics — week ending {day}",
            "description": description,
        },
    }

    if not ALARM_TOPIC_ARN:
        logger.warning("ALARM_TOPIC_ARN not set — printing digest instead of posting")
        logger.info(description)
        return {"posted": False, "description": description}

    boto3.client("sns").publish(
        TopicArn=ALARM_TOPIC_ARN,
        Message=json.dumps(payload),
        Subject="Sarathi weekly product metrics",
    )
    logger.info("Posted weekly digest for %s", day)
    return {"posted": True, "day": day}

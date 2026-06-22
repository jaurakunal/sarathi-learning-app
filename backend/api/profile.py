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


def _build_insights(
    read_papers, asked_papers, source_click_papers, dismissed_papers,
    section_counts, total_active_ms, impressions, views, areas, conv_turns,
) -> list[dict]:
    """Generate plain-language insights about what the system is observing."""
    insights = []

    # Section preferences
    top_section = max(section_counts, key=section_counts.get) if any(section_counts.values()) else None
    if top_section and section_counts[top_section] > 2:
        section_labels = {"deep_dive": "Deep Dive", "glossary": "Glossary", "math_notes": "Math Notes", "other": "other sections"}
        insights.append({
            "icon": "📊",
            "text": f"You expand {section_labels.get(top_section, top_section)} most often ({section_counts[top_section]}x this week) — serving you deeper content in that style",
        })

    # Area heat (only show if Learn step has run and set meaningful statuses)
    hot_areas = [a for a in areas if a.get("status") == "hot"]
    for a in hot_areas[:1]:
        insights.append({
            "icon": "🔥",
            "text": f"{a.get('name', a.get('id'))} is your hottest area — weighting discovery toward this",
        })

    cold_areas = [a for a in areas if a.get("status") in ("cool", "dormant")]
    for a in cold_areas[:1]:
        insights.append({
            "icon": "❄️",
            "text": f"{a.get('name', a.get('id'))}: no recent engagement — cooling it down in discovery",
        })

    # Questions asked (depth signal)
    if asked_papers:
        total_turns = sum(conv_turns.values())
        if total_turns > 5:
            insights.append({
                "icon": "💬",
                "text": f"You asked questions about {len(asked_papers)} paper{'s' if len(asked_papers) > 1 else ''} ({total_turns} total turns) — this signals deep interest",
            })

    # Source clicks (went beyond the digest)
    if source_click_papers:
        insights.append({
            "icon": "📄",
            "text": f"You clicked through to {len(source_click_papers)} full paper{'s' if len(source_click_papers) > 1 else ''} — the digest alone wasn't enough",
        })

    # Reading speed estimate
    if total_active_ms > 0 and read_papers:
        avg_ms_per_paper = total_active_ms / len(read_papers)
        avg_min = round(avg_ms_per_paper / 60000, 1)
        insights.append({
            "icon": "⏱️",
            "text": f"Average reading time: {avg_min} min per paper (across {len(read_papers)} read)",
        })

    # Funnel: unique papers seen (viewed) → reads
    # Use views (unique card opens) as the top of funnel, not raw impressions
    if views > 0:
        read_rate = round(len(read_papers) / views * 100)
        insights.append({
            "icon": "📈",
            "text": f"Funnel: {views} papers opened → {len(read_papers)} read deeply ({read_rate}%)",
        })

    return insights


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

    # 2b. Latest weekly brief
    brief_resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}#BRIEF"),
        ScanIndexForward=False,
        Limit=1,
    )
    brief_items = brief_resp.get("Items", [])
    latest_brief = None
    if brief_items:
        b = brief_items[0]
        latest_brief = {
            "week": b.get("week", ""),
            "content": b.get("content", ""),
            "created_at": b.get("created_at", ""),
            "stats": b.get("stats", {}),
        }

    # 3. Engagement stats for the last 7 days
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = db.list_engagement_events(table, user_id, since, now)

    # Aggregate stats (unique papers, not event counts)
    read_papers: set = set()
    dismissed_papers: set = set()
    bookmarked_papers: set = set()
    asked_papers: set = set()
    source_click_papers: set = set()
    total_active_ms = 0
    sections_expanded = 0
    section_counts: dict = {"glossary": 0, "deep_dive": 0, "math_notes": 0, "other": 0}
    impressions = 0
    views = 0

    for e in events:
        action = e.get("action", "")
        paper_id = e.get("paper_id", "")
        if action == "read":
            read_papers.add(paper_id)
            if e.get("active_ms"):
                total_active_ms += int(e["active_ms"])
        elif action == "dismiss":
            dismissed_papers.add(paper_id)
        elif action == "bookmark":
            bookmarked_papers.add(paper_id)
        elif action == "ask":
            asked_papers.add(paper_id)
        elif action == "source_click":
            source_click_papers.add(paper_id)
        elif action == "expand":
            sections_expanded += 1
            section = e.get("section", "other")
            if section in section_counts:
                section_counts[section] += 1
            else:
                section_counts["other"] += 1
        elif action == "impression":
            impressions += 1
        elif action == "view":
            views += 1

    stats = {
        "papers_read": len(read_papers),
        "papers_dismissed": len(dismissed_papers),
        "papers_bookmarked": len(bookmarked_papers),
        "questions_asked": len(asked_papers),
        "source_clicks": len(source_click_papers),
        "sections_expanded": sections_expanded,
        "total_active_ms": total_active_ms,
    }

    # 3b. Get conversation turn counts for insights
    conv_resp = table.query(
        IndexName="GSI1",
        KeyConditionExpression=(
            Key("gsi1pk").eq(f"USER#{user_id}")
            & Key("gsi1sk").begins_with("CONV#")
        ),
    )
    conv_turns: dict[str, int] = {}
    for c in conv_resp.get("Items", []):
        conv_id = c.get("conv_id", "")
        turn_count = int(c.get("turn_count", 0))
        if conv_id:
            conv_turns[conv_id] = turn_count

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
        "latest_brief": latest_brief,
        "insights": _build_insights(
            read_papers, asked_papers, source_click_papers, dismissed_papers,
            section_counts, total_active_ms, impressions, views, areas, conv_turns,
        ),
    })

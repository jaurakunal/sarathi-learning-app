"""Generate a weekly deep brief — synthesized summary of the user's learning week.

Can be triggered manually or scheduled (e.g., every Monday).
Reads: engagement events, conversations, profile, feed cards from the past 7 days.
Writes: a brief item to DDB (USER#<sub>#BRIEF, SK=WEEK#<iso_date>).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db
from backend.shared.llm import call_llm
from backend.pipeline.learn import _aggregate_engagement, _collect_conversations

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"

BRIEF_SYSTEM_PROMPT = """You write weekly learning briefs for a research learner. Your tone is: sharp, honest, no flattery, concise. Like a mentor who respects their time.

You produce a brief that:
1. Opens with the single most important thing that happened this week (one sentence)
2. Summarizes what was read and how deeply (2-3 sentences)
3. Identifies the key insight or question that emerged from conversations
4. Notes how the user's frontier moved (what they know now that they didn't a week ago)
5. Gives 1-2 forward-looking suggestions (what to read next, what gap to fill)

Rules:
- Never say "great job" or "well done." The brief is informational, not motivational.
- Be specific — name papers, quote questions, reference actual engagement.
- If the week was light (few papers, no questions), say so honestly and suggest why.
- Keep total length to 150-250 words. Dense, not verbose.
- Use markdown formatting (bold for emphasis, bullet points for suggestions).

Output the brief as plain text (markdown). Not JSON."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def handler(event: dict, context) -> dict:
    """Generate and store a weekly brief."""
    user_id = event["user_id"]
    workspace_id = event.get("workspace_id", "")
    table_name = event["table_name"]
    model_id = event.get("model", DEFAULT_MODEL)

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    if not workspace_id:
        workspace_id = db.get_active_workspace(table, user_id) or ""

    # Time window: last 7 days
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    week_key = now.strftime("%Y-%m-%d")

    # 1. Get profile (workspace-scoped)
    profile = db.get_full_profile(table, user_id, workspace_id)
    if not profile.get("meta"):
        return {"status": "skipped", "reason": "no_profile"}

    # 2. Get engagement events
    events = db.list_engagement_events(table, user_id, workspace_id, since, now_ts)
    stats = _aggregate_engagement(events)

    # 3. Get conversations
    conversations = _collect_conversations(table, user_id, workspace_id, since)

    # 4. Get frontier snapshots from profile history (this week's learn runs)
    history_resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(db._profile_history_pk(user_id, workspace_id))
            & Key("SK").gte(f"TS#{since}")
        ),
        ScanIndexForward=True,
    )
    history_items = history_resp.get("Items", [])
    frontier_changes = []
    for h in history_items:
        if h.get("frontier_snapshots"):
            for area_id, snap in h["frontier_snapshots"].items():
                frontier_changes.append({
                    "area": area_id,
                    "before": snap.get("before", {}).get("frontier", ""),
                    "after": snap.get("after", {}).get("frontier", ""),
                })

    # 5. Get feed cards from this week (what was served, workspace-scoped)
    cards_resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(db._feed_pk(user_id, workspace_id))
            & Key("SK").begins_with("CARD#")
        ),
        ScanIndexForward=False,
        Limit=20,
    )
    cards = cards_resp.get("Items", [])
    recent_card_titles = [c.get("hook", "")[:80] for c in cards if c.get("created_at", "") >= since]

    # 6. Check if there's enough to brief on
    if stats["total_events"] == 0 and not conversations:
        # Store a "quiet week" brief
        brief_text = "**Quiet week.** No papers read, no questions asked. The pipeline ran but nothing caught your attention — either the hooks missed, or life got in the way. No judgment. Come back when you're ready."
    else:
        # 7. Build prompt
        user_message = _build_brief_prompt(profile, stats, conversations, frontier_changes, recent_card_titles)

        brief_text = call_llm(
            system=BRIEF_SYSTEM_PROMPT,
            user_message=user_message,
            model_id=model_id,
            max_tokens=1024,
            temperature=0.4,
        )

        if not brief_text:
            return {"status": "error", "reason": "llm_failed"}

    # 8. Store the brief (workspace-scoped)
    table.put_item(Item={
        "PK": db._brief_pk(user_id, workspace_id),
        "SK": f"WEEK#{week_key}",
        "user_id": user_id,
        "workspace_id": workspace_id,
        "week": week_key,
        "content": brief_text,
        "created_at": now_ts,
        "stats": {
            "papers_read": len(stats.get("papers_read", [])),
            "questions_asked": len(conversations),
            "source_clicks": len(stats.get("source_clicks", [])),
        },
    })

    logger.info("Weekly brief generated for %s (week %s)", user_id, week_key)
    return {"status": "ok", "week": week_key}


def _build_brief_prompt(
    profile: dict,
    stats: dict,
    conversations: list[dict],
    frontier_changes: list[dict],
    card_titles: list[str],
) -> str:
    parts = []

    # Current profile context
    parts.append("<profile>")
    for area in profile.get("areas", []):
        parts.append(f"Area: {area.get('name', area.get('id'))} — frontier: {area.get('frontier', '')[:100]}")
    if profile.get("hypothesis"):
        parts.append(f"Hypothesis: {profile['hypothesis'].get('statement', '')}")
    parts.append("</profile>")

    # Engagement stats
    parts.append(f"\n<engagement_this_week>")
    parts.append(f"Papers read: {len(stats.get('papers_read', []))}")
    parts.append(f"Papers dismissed: {len(stats.get('papers_dismissed', []))}")
    parts.append(f"Source clicks (went to full paper): {len(stats.get('source_clicks', []))}")
    parts.append(f"Sections expanded: glossary={stats['sections_expanded'].get('glossary',0)}, deep_dive={stats['sections_expanded'].get('deep_dive',0)}, math_notes={stats['sections_expanded'].get('math_notes',0)}")
    parts.append(f"Total active reading time: {stats.get('total_active_ms', 0) // 1000}s")
    parts.append("</engagement_this_week>")

    # Conversations
    if conversations:
        parts.append(f"\n<conversations_this_week>")
        for conv in conversations:
            parts.append(f"Paper: {conv['paper_id']}")
            for turn in conv["turns"][:3]:
                parts.append(f"  Q: {turn['question'][:100]}")
        parts.append("</conversations_this_week>")

    # Frontier changes
    if frontier_changes:
        parts.append(f"\n<frontier_movement>")
        for fc in frontier_changes:
            parts.append(f"{fc['area']}:")
            parts.append(f"  Was: {fc['before'][:80]}")
            parts.append(f"  Now: {fc['after'][:80]}")
        parts.append("</frontier_movement>")

    # What was served
    if card_titles:
        parts.append(f"\n<cards_served_this_week>")
        for t in card_titles[:10]:
            parts.append(f"  • {t}")
        parts.append("</cards_served_this_week>")

    parts.append("\nWrite the weekly brief now.")
    return "\n".join(parts)

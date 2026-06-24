"""Pipeline step: Nightly learning loop.

Reads engagement events + conversation turns since last run, calls the LLM
to analyze patterns, and updates the user's profile (frontiers, hypothesis,
summaries, reading speed, area status).
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

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"

LEARN_SYSTEM_PROMPT = """You are updating a research learner's profile based on their engagement data from the past period.

Your job: analyze what the user read, skipped, asked about, and rated — then update their profile to reflect how they've grown, what they're interested in, and what level they're at.

Rules:
- Be precise about what changed vs what stayed the same. Don't inflate progress.
- If there's not enough signal to update something, say so and leave it unchanged.
- Interest intensity comes from behavior, not from what the user says they want.
- A paper that got "ask" + multiple chat turns + source_click = deep engagement. A paper that got view + quick dismiss = poor match.
- Section preferences (which sections they expand) reveal learning style and readiness for depth.
- Question sophistication reveals level: definitional ("what is X") → comparative ("how does X differ from Y") → applied ("how would I use X for my project") → critical ("what breaks if we relax this assumption").
- Hypothesis evidence: look for conversation content that directly supports, refutes, or refines the user's stated hypothesis.

Output valid JSON matching the schema below. Only include fields that actually changed."""


LEARN_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "areas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area_id": {"type": "string"},
                    "frontier": {"type": "string", "description": "Updated prose describing the current knowledge edge"},
                    "status": {"type": "string", "enum": ["hot", "warm", "cool", "dormant"]},
                },
                "required": ["area_id"],
            },
            "description": "Only include areas that changed",
        },
        "hypothesis_evidence": {
            "type": "object",
            "properties": {
                "supporting": {"type": "array", "items": {"type": "string"}},
                "refuting": {"type": "array", "items": {"type": "string"}},
                "refining": {"type": "array", "items": {"type": "string"}},
            },
            "description": "New evidence found in this period's conversations",
        },
        "learning_style": {
            "type": "object",
            "properties": {
                "prefers_depth": {"type": "boolean", "description": "True if user regularly expands deep_dive sections"},
                "engages_math": {"type": "boolean", "description": "True if user expands math_notes"},
                "asks_applied": {"type": "boolean", "description": "True if questions are application-focused"},
            },
        },
        "reading_speed_wpm": {
            "type": "number",
            "description": "Estimated words per minute based on active_ms vs content length. Null if insufficient data.",
        },
        "summaries": {
            "type": "object",
            "properties": {
                "yesterday": {"type": "string"},
                "three_day": {"type": "string"},
                "seven_day": {"type": "string"},
                "month": {"type": "string"},
                "quarter": {"type": "string"},
            },
            "description": "Regenerated tiered summaries of user activity",
        },
        "changelog": {
            "type": "string",
            "description": "1-3 sentence summary of what changed in this update, for the audit trail",
        },
    },
    "required": ["changelog", "summaries"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _aggregate_engagement(events: list[dict]) -> dict:
    """Summarize engagement events into structured stats for the LLM."""
    stats: dict[str, Any] = {
        "total_events": len(events),
        "papers_read": [],
        "papers_dismissed": [],
        "papers_bookmarked": [],
        "papers_rated_up": [],
        "papers_rated_down": [],
        "sections_expanded": {"glossary": 0, "deep_dive": 0, "math_notes": 0, "other": 0},
        "source_clicks": [],
        "total_active_ms": 0,
        "avg_scroll_depth": 0,
        "impressions": 0,
        "views": 0,
    }

    scroll_depths = []

    for e in events:
        action = e.get("action", "")
        paper_id = e.get("paper_id", "")

        if action == "read":
            stats["papers_read"].append(paper_id)
            if e.get("active_ms"):
                stats["total_active_ms"] += int(e["active_ms"])
            if e.get("scroll_depth_pct"):
                scroll_depths.append(int(e["scroll_depth_pct"]))
        elif action == "dismiss":
            stats["papers_dismissed"].append(paper_id)
        elif action == "bookmark":
            stats["papers_bookmarked"].append(paper_id)
        elif action == "rate":
            rating = int(e.get("rating", 0))
            if rating >= 4:
                stats["papers_rated_up"].append(paper_id)
            elif rating <= 2 and rating > 0:
                stats["papers_rated_down"].append(paper_id)
        elif action == "expand":
            section = e.get("section", "other")
            if section in stats["sections_expanded"]:
                stats["sections_expanded"][section] += 1
            else:
                stats["sections_expanded"]["other"] += 1
        elif action == "source_click":
            stats["source_clicks"].append(paper_id)
        elif action == "impression":
            stats["impressions"] += 1
        elif action == "view":
            stats["views"] += 1

    if scroll_depths:
        stats["avg_scroll_depth"] = round(sum(scroll_depths) / len(scroll_depths))

    # Dedupe paper lists
    stats["papers_read"] = list(set(stats["papers_read"]))
    stats["papers_dismissed"] = list(set(stats["papers_dismissed"]))
    stats["papers_bookmarked"] = list(set(stats["papers_bookmarked"]))
    stats["source_clicks"] = list(set(stats["source_clicks"]))

    return stats


def _collect_conversations(table, user_id: str, since_ts: str) -> list[dict]:
    """Collect conversation turns since the given timestamp."""
    # Query all conversations via GSI1
    resp = table.query(
        IndexName="GSI1",
        KeyConditionExpression=(
            Key("gsi1pk").eq(f"USER#{user_id}")
            & Key("gsi1sk").begins_with("CONV#")
        ),
    )

    conversations = []
    for conv_meta in resp.get("Items", []):
        conv_id = conv_meta.get("conv_id", "")
        if not conv_id:
            continue

        turns = db.get_conversation_turns(table, user_id, conv_id)
        # Filter to turns since last learn
        new_turns = [
            t for t in turns
            if t.get("request_ts", "") > since_ts and t.get("response")
        ]

        if new_turns:
            conversations.append({
                "paper_id": conv_meta.get("paper_id", conv_id),
                "turns": [
                    {"question": t.get("request", ""), "answer": t.get("response", "")}
                    for t in new_turns
                ],
            })

    return conversations


def _build_learn_prompt(
    profile: dict,
    engagement_stats: dict,
    conversations: list[dict],
) -> str:
    """Build the user message for the Learn LLM call."""
    parts = []

    # Current profile
    parts.append("<current_profile>")
    if profile.get("meta"):
        parts.append(f"Learning style: {json.dumps(profile['meta'].get('learning_style', {}))}")
        parts.append(f"Reading speed: {profile['meta'].get('reading_speed', 'unknown')}")
    for area in profile.get("areas", []):
        parts.append(f"\nArea: {area.get('name', area.get('id', '?'))}")
        parts.append(f"  Status: {area.get('status', 'unknown')}")
        parts.append(f"  Frontier: {area.get('frontier', 'not set')}")
    if profile.get("hypothesis"):
        h = profile["hypothesis"]
        parts.append(f"\nHypothesis: {h.get('statement', '')}")
        parts.append(f"  Supporting: {h.get('supporting', [])}")
        parts.append(f"  Refuting: {h.get('refuting', [])}")
    parts.append("</current_profile>")

    # Engagement stats
    parts.append("\n<engagement_since_last_update>")
    parts.append(f"Papers read: {len(engagement_stats['papers_read'])} ({engagement_stats['papers_read']})")
    parts.append(f"Papers dismissed: {len(engagement_stats['papers_dismissed'])} ({engagement_stats['papers_dismissed']})")
    parts.append(f"Papers bookmarked: {engagement_stats['papers_bookmarked']}")
    parts.append(f"Papers rated up: {engagement_stats['papers_rated_up']}")
    parts.append(f"Papers rated down: {engagement_stats['papers_rated_down']}")
    parts.append(f"Source link clicks (went to full paper): {engagement_stats['source_clicks']}")
    parts.append(f"Sections expanded: {json.dumps(engagement_stats['sections_expanded'])}")
    parts.append(f"Total active reading time: {engagement_stats['total_active_ms']}ms")
    parts.append(f"Average scroll depth: {engagement_stats['avg_scroll_depth']}%")
    parts.append(f"Impressions (cards seen in feed): {engagement_stats['impressions']}")
    parts.append(f"Views (cards opened): {engagement_stats['views']}")
    parts.append("</engagement_since_last_update>")

    # Conversations
    if conversations:
        parts.append("\n<conversations_since_last_update>")
        for conv in conversations:
            parts.append(f"\n[Paper: {conv['paper_id']}]")
            for turn in conv["turns"]:
                parts.append(f"  Q: {turn['question']}")
                parts.append(f"  A: {turn['answer'][:500]}{'...' if len(turn['answer']) > 500 else ''}")
        parts.append("</conversations_since_last_update>")
    else:
        parts.append("\n<conversations_since_last_update>No new conversations.</conversations_since_last_update>")

    parts.append("\nAnalyze the above and return the JSON update.")
    return "\n".join(parts)


def handler(event: dict, context) -> dict:
    """Lambda handler for the Learn step."""
    user_id = event["user_id"]
    table_name = event["table_name"]
    model_id = event.get("model", DEFAULT_MODEL)

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # 1. Get current profile
    profile = db.get_full_profile(table, user_id)
    if not profile.get("meta"):
        logger.warning("No profile found for user %s — skipping learn step", user_id)
        return {"status": "skipped", "reason": "no_profile"}

    # 2. Determine time window (since last learn, or last 7 days)
    last_learn_ts = profile["meta"].get("last_learn_ts")
    if not last_learn_ts:
        # First run — look back 7 days
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        since = last_learn_ts

    # 3. Read engagement events since last run
    now_ts = _now_iso()
    events = db.list_engagement_events(table, user_id, since, now_ts)
    logger.info("Found %d engagement events since %s", len(events), since)

    # 4. Aggregate engagement stats
    engagement_stats = _aggregate_engagement(events)

    # 5. Collect new conversation turns
    conversations = _collect_conversations(table, user_id, since)
    logger.info("Found %d conversations with new turns", len(conversations))

    # 6. Check if there's enough signal to justify an LLM call
    if engagement_stats["total_events"] == 0 and not conversations:
        logger.info("No engagement or conversations since last run — skipping")
        # Still update last_learn_ts so we don't re-scan
        db.put_profile_meta(table, user_id, {**profile["meta"], "last_learn_ts": now_ts})
        # Mark pipeline as succeeded (learn is the last step)
        db.update_pipeline_status(table, user_id, "succeeded")
        return {"status": "skipped", "reason": "no_activity"}

    # 7. Build prompt and call LLM
    user_message = _build_learn_prompt(profile, engagement_stats, conversations)

    llm_response = call_llm(
        system=LEARN_SYSTEM_PROMPT,
        user_message=user_message,
        model_id=model_id,
        max_tokens=8192,
        temperature=0.3,
    )

    if not llm_response:
        logger.error("LLM call failed for learn step")
        return {"status": "error", "reason": "llm_failed"}

    # 8. Parse structured output
    try:
        # Strip markdown code fences if present
        text = llm_response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        updates = json.loads(text)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error("Failed to parse LLM response as JSON: %s", str(e)[:200])
        logger.debug("Raw response: %s", llm_response[:500])
        return {"status": "error", "reason": "parse_failed"}

    # 9. Apply updates to DDB
    changes_made = []

    # Normalize areas format — LLM may return as array or as object keyed by area_id
    raw_areas = updates.get("areas", [])
    area_updates = []
    if isinstance(raw_areas, dict):
        # Object format: {"area_id": {...fields...}, ...}
        for area_id, fields in raw_areas.items():
            if isinstance(fields, dict):
                area_updates.append({"area_id": area_id, **fields})
    elif isinstance(raw_areas, list):
        area_updates = [a for a in raw_areas if isinstance(a, dict)]

    # Update areas (track before/after for history)
    frontier_snapshots = {}
    for area_update in area_updates:
        area_id = area_update.get("area_id")
        if not area_id:
            continue
        # Find existing area
        existing = next((a for a in profile.get("areas", []) if a.get("id") == area_id), None)
        if existing:
            before_frontier = existing.get("frontier", "")
            before_status = existing.get("status", "")
            if area_update.get("frontier"):
                existing["frontier"] = area_update["frontier"]
            if area_update.get("status"):
                existing["status"] = area_update["status"]
            existing["last_engaged"] = now_ts
            db.put_profile_area(table, user_id, existing)
            changes_made.append(f"area:{area_id}")
            frontier_snapshots[area_id] = {
                "before": {"frontier": before_frontier, "status": before_status},
                "after": {"frontier": existing.get("frontier", ""), "status": existing.get("status", "")},
            }

    # Update hypothesis evidence
    hyp_evidence = updates.get("hypothesis_evidence", {})
    if any(hyp_evidence.get(k) for k in ("supporting", "refuting", "refining")):
        existing_hyp = profile.get("hypothesis") or {}
        for key in ("supporting", "refuting", "refining"):
            new_items = hyp_evidence.get(key, [])
            if new_items:
                existing_list = existing_hyp.get(key, [])
                existing_hyp[key] = existing_list + new_items
        db.put_profile_hypothesis(table, user_id, existing_hyp)
        changes_made.append("hypothesis")

    # Update learning style + reading speed on META
    meta_updates = {**profile["meta"], "last_learn_ts": now_ts}
    if updates.get("learning_style"):
        meta_updates["learning_style"] = updates["learning_style"]
        changes_made.append("learning_style")
    if updates.get("reading_speed_wpm"):
        meta_updates["reading_speed"] = updates["reading_speed_wpm"]
        changes_made.append("reading_speed")
    db.put_profile_meta(table, user_id, meta_updates)

    # Update summaries
    summaries = updates.get("summaries", {})
    tier_map = {
        "yesterday": "yesterday",
        "three_day": "3_day",
        "seven_day": "7_day",
        "month": "month",
        "quarter": "quarter",
    }
    for key, tier in tier_map.items():
        content = summaries.get(key, "")
        if content:
            db.put_profile_summary(table, user_id, tier, content)
    if summaries:
        changes_made.append("summaries")

    # 10. Write profile history event with frontier snapshots
    changelog = updates.get("changelog", "Learn step ran with no changelog.")
    history_event = {
        "ts": now_ts,
        "type": "learn_update",
        "changes": changes_made,
        "changelog": changelog,
    }
    if frontier_snapshots:
        history_event["frontier_snapshots"] = frontier_snapshots
    if hyp_evidence and any(hyp_evidence.get(k) for k in ("supporting", "refuting", "refining")):
        history_event["hypothesis_evidence_added"] = hyp_evidence
    db.put_profile_history_event(table, user_id, history_event)

    # Mark pipeline as succeeded (learn is the last step in the pipeline)
    db.update_pipeline_status(table, user_id, "succeeded")

    logger.info("Learn step complete: %s", changes_made)
    return {
        "status": "ok",
        "changes": changes_made,
        "changelog": changelog,
    }

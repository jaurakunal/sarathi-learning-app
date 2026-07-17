"""Assemble a research-proposal context from a workspace's accumulated signal.

The output feeds two downstream renderers:
  - render_bundle_md(): deterministic markdown "context pack" the user can
    paste into any LLM.
  - render_proposal_md(): a single LLM pass that turns the context into a
    proposal-shaped draft (problem → approach → existing research → what's
    new → next steps).

The context bundles the durable signals the user has generated:
  - profile: hypothesis + selected area(s) + background/learning style
  - papers: digested feed cards (hook, why_you_now, digest summary),
    optionally filtered to one area
  - pinned insights: turns the user pinned in paper chats — the actual quote
    plus which paper it came from
  - recent research questions: last N turns in research conversations, so
    the doc knows what the user has been actively wondering about
  - engagement signals: high-level counts (dismissed / bookmarked / read),
    NOT a per-event dump
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.shared import db

logger = logging.getLogger(__name__)

# Bounds — anything above these gets truncated with a log line.
MAX_PAPERS = 15
MAX_PINNED_INSIGHTS = 10
MAX_RECENT_QUESTIONS = 20


@dataclass
class PaperCtx:
    """A single paper summary suitable for a proposal context."""
    paper_id: str
    title: str
    authors: list[str]
    source: str
    url: str
    hook: str
    why_you_now: str
    digest_gist: str
    key_ideas: list[str]
    areas_matched: list[str]


@dataclass
class PinnedInsightCtx:
    """A quote the user pinned from a paper chat."""
    paper_title: str
    paper_id: str
    question: str
    answer: str


@dataclass
class EngagementCtx:
    """High-level counts, one paragraph's worth of signal."""
    dismissed: int = 0
    bookmarked: int = 0
    bounced: int = 0
    source_clicked: int = 0
    read_fully: int = 0
    pinned_turns: int = 0


@dataclass
class ProposalContext:
    """Everything a proposal renderer needs about a workspace."""
    workspace_name: str
    area_name: str
    area_description: str
    hypothesis_statement: str
    background: str
    learning_style: str
    papers: list[PaperCtx] = field(default_factory=list)
    pinned_insights: list[PinnedInsightCtx] = field(default_factory=list)
    recent_questions: list[str] = field(default_factory=list)
    engagement: EngagementCtx = field(default_factory=EngagementCtx)
    truncation_notes: list[str] = field(default_factory=list)


def _extract_digest_gist(digest: dict) -> tuple[str, list[str]]:
    """Pull the short 'gist' and 'key_ideas' bullets out of a digest blob."""
    if not isinstance(digest, dict):
        return "", []
    gist = digest.get("gist") or digest.get("summary") or ""
    key_ideas = digest.get("key_ideas") or digest.get("bullets") or []
    if not isinstance(key_ideas, list):
        key_ideas = []
    return str(gist).strip(), [str(k).strip() for k in key_ideas if k]


def _paper_matches_area(card: dict, area_name: str) -> bool:
    """Does this card's areas_matched list include the given area?"""
    if not area_name:
        return True
    matched = card.get("areas_matched") or []
    if not isinstance(matched, list):
        return False
    return any(a and area_name.lower() in str(a).lower() for a in matched)


def assemble_context(
    table,
    user_id: str,
    workspace_id: str,
    area_id: Optional[str] = None,
) -> ProposalContext:
    """Build a proposal context for one workspace, optionally scoped to one area.

    ``area_id`` refers to the AREA# SK suffix. When set, papers are filtered
    by matching the area's name against each card's ``areas_matched`` list.
    """
    # 1. Profile: workspace-level META (hypothesis, area names, description)
    #    plus user-level META (background, learning_style, math_comfort).
    full_profile = db.get_full_profile(table, user_id, workspace_id)
    ws = db.get_workspace(table, user_id, workspace_id) or {}
    workspace_name = ws.get("name", "Workspace")
    user_meta = db.get_user_meta(table, user_id) or {}
    background = user_meta.get("background", "")
    learning_style = user_meta.get("learning_style", "")

    hypothesis = (full_profile.get("hypothesis") or {}).get("statement", "")

    # Resolve the target area (or all areas)
    all_areas = full_profile.get("areas") or []
    area_name = ""
    area_description = ""
    if area_id:
        for a in all_areas:
            if a.get("id") == area_id or a.get("SK", "") == f"AREA#{area_id}":
                area_name = a.get("name", "")
                area_description = a.get("description", "") or a.get("goal", "")
                break
        if not area_name:
            logger.info("area_id %s not found — falling back to workspace-wide", area_id)
    if not area_name:
        # workspace-wide: concatenate area names as a rough label
        names = [a.get("name", "") for a in all_areas if a.get("name")]
        area_name = ", ".join(names) if names else workspace_name
        area_description = ws.get("description", "") or ""

    ctx = ProposalContext(
        workspace_name=workspace_name,
        area_name=area_name,
        area_description=area_description,
        hypothesis_statement=hypothesis,
        background=background,
        learning_style=learning_style,
    )

    # 2. Papers — pull digested feed cards, filter by area, cap.
    # We use feed cards (not paper records) because that's where hook /
    # why_you_now / digest live.
    all_cards: list[dict] = []
    last_key = None
    # Pull up to a few pages to have enough to filter from.
    for _ in range(5):
        page, last_key = db.list_feed_cards(
            table, user_id, workspace_id, limit=50, last_key=last_key,
        )
        all_cards.extend(page)
        if not last_key or len(all_cards) >= 200:
            break

    # Filter to matching area (if any) and cap.
    filtered = [c for c in all_cards if _paper_matches_area(c, area_name if area_id else "")]
    total_available = len(filtered)
    if total_available > MAX_PAPERS:
        ctx.truncation_notes.append(
            f"Included the {MAX_PAPERS} most recent papers; {total_available - MAX_PAPERS} more available."
        )
        logger.info(
            "assemble_context: capped papers %d -> %d for user=%s ws=%s",
            total_available, MAX_PAPERS, user_id, workspace_id,
        )
    for card in filtered[:MAX_PAPERS]:
        digest = card.get("digest") or {}
        gist, key_ideas = _extract_digest_gist(digest)
        ctx.papers.append(PaperCtx(
            paper_id=card.get("paper_id", ""),
            title=card.get("title", "") or "Untitled",
            authors=list(card.get("authors", []) or []),
            source=card.get("source", "") or "",
            url=card.get("source_url", "") or card.get("url", "") or "",
            hook=card.get("hook", "") or "",
            why_you_now=card.get("why_you_now", "") or "",
            digest_gist=gist,
            key_ideas=key_ideas,
            areas_matched=list(card.get("areas_matched", []) or []),
        ))

    # 3. Pinned insights — walk conversations, collect pinned turns.
    # Count all pinned turns first (for reading-signals accuracy) even
    # after the collection cap is reached.
    conversations = db.list_all_conversations(table, user_id, workspace_id) or []
    pinned_count_total = 0
    for conv in conversations:
        conv_id = conv.get("conv_id") or (conv.get("SK", "").replace("CONV#", ""))
        if not conv_id:
            continue
        pinned = db.get_pinned_turns(table, user_id, workspace_id, conv_id) or []
        pinned_count_total += len(pinned)
        for turn in pinned:
            if len(ctx.pinned_insights) >= MAX_PINNED_INSIGHTS:
                continue
            ctx.pinned_insights.append(PinnedInsightCtx(
                paper_title=conv.get("title", "") or "Untitled",
                paper_id=conv.get("paper_id", "") or "",
                question=turn.get("request", "") or "",
                answer=turn.get("response", "") or "",
            ))
    ctx.engagement.pinned_turns = pinned_count_total
    if pinned_count_total > MAX_PINNED_INSIGHTS:
        ctx.truncation_notes.append(
            f"Included the first {MAX_PINNED_INSIGHTS} pinned insights; {pinned_count_total - MAX_PINNED_INSIGHTS} more exist."
        )

    # 4. Recent research questions — pull the newest N turns from
    # research conversations (not paper chats — those live under pinned).
    q_collected = 0
    for conv in conversations:
        if q_collected >= MAX_RECENT_QUESTIONS:
            break
        # research convs have paper_id empty and a distinct type marker; be
        # lenient about the schema and just include any conv turns.
        conv_id = conv.get("conv_id") or (conv.get("SK", "").replace("CONV#", ""))
        if not conv_id:
            continue
        turns = db.get_conversation_turns(table, user_id, workspace_id, conv_id) or []
        # newest turns first
        for turn in reversed(turns):
            req = (turn.get("request") or "").strip()
            if not req:
                continue
            ctx.recent_questions.append(req)
            q_collected += 1
            if q_collected >= MAX_RECENT_QUESTIONS:
                break

    # 5. Engagement counts — one paragraph's worth.
    # Query engagement PK directly (list_engagement_events requires a time
    # range; here we just want workspace-wide totals).
    from boto3.dynamodb.conditions import Key as _Key
    resp = table.query(
        KeyConditionExpression=_Key("PK").eq(db._engagement_pk(user_id, workspace_id)),
    )
    events = resp.get("Items", []) or []
    for e in events:
        action = (e.get("action") or "").lower()
        if action == "dismiss":
            ctx.engagement.dismissed += 1
        elif action in ("bookmark", "save"):
            ctx.engagement.bookmarked += 1
        elif action == "bounce":
            ctx.engagement.bounced += 1
        elif action in ("source_click", "click_source"):
            ctx.engagement.source_clicked += 1
        elif action in ("read", "read_fully", "read_full"):
            ctx.engagement.read_fully += 1

    return ctx

"""Pipeline step: Connect — link a newly digested paper to the user's library.

Runs after Lens. For each paper card digested in the last day, look for a
paper the user has already engaged with that makes a specific, checkable
claim the new paper supports, contradicts, or extends. When one is found,
write a ``connect`` feed card saying exactly how the two relate.

A weak "these are both about memory" card is worse than no card, so the step
is deliberately stingy:

  1. Vector prefilter — the new paper's summary must land near a section of
     an engaged paper (cosine distance <= CONNECT_MAX_DISTANCE).
  2. LLM gate — the model is told to default to "not connected" and must name
     a specific claim from each paper.
  3. Caps — CONNECT_MAX_PER_RUN per pipeline run, CONNECT_MAX_PER_WEEK per
     rolling 7 days, and never the same pair twice.

This step never fails the pipeline: any error yields zero cards.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3

from backend.shared import db, metrics
from backend.shared.llm import call_llm_with_fallback

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_MODEL = os.environ.get("CONNECT_MODEL", "moonshotai.kimi-k2.5")
FALLBACK_MODEL = "us.anthropic.claude-sonnet-4-6"

# Cosine distance (0 = identical). A cheap prefilter only — the LLM gate is
# the real quality bar. Not yet calibrated against production data.
MAX_DISTANCE = float(os.environ.get("CONNECT_MAX_DISTANCE", "0.6"))
MAX_PER_RUN = int(os.environ.get("CONNECT_MAX_PER_RUN", "1"))
MAX_PER_WEEK = int(os.environ.get("CONNECT_MAX_PER_WEEK", "2"))
# Upper bound on LLM gate calls per run, so a noisy night stays cheap.
MAX_LLM_ATTEMPTS = int(os.environ.get("CONNECT_MAX_LLM_ATTEMPTS", "3"))
NEW_CARD_WINDOW_HOURS = int(os.environ.get("CONNECT_NEW_CARD_WINDOW_HOURS", "36"))

# Engagement that means "this paper is part of my library".
LIBRARY_ACTIONS = {"read", "bookmark", "ask", "pin", "tag"}
VALID_RELATIONS = {"supports", "contradicts", "extends"}

SYSTEM_PROMPT = """You decide whether two research papers have a connection worth a reader's two minutes, for Sarathi, a personal research tool.

The reader has already engaged with PAPER A. PAPER B arrived today. Say whether B specifically supports, contradicts, or extends a claim made in A.

Rules:
- Default to NOT connected. Sharing a topic, a method family, or a benchmark is not a connection.
- A connection needs one specific claim or result from A and one from B that bear on each other. If you cannot name both from the text given, it is not connected.
- "contradicts" only if the results or claims genuinely conflict — not merely different settings.
- Never flatter and never inflate. Do not call anything novel or groundbreaking.
- Plain language, no equations. The reader is a practitioner, not an academic.

Return ONLY a JSON object, no prose and no code fences:
{
  "connected": true | false,
  "relation": "supports" | "contradicts" | "extends" | "none",
  "hook": "one provocative but honest sentence naming the tension or link (max 25 words)",
  "why_it_matters": "one sentence on what this changes for the reader's work or hypothesis",
  "claim_a": "the specific claim from PAPER A, one sentence",
  "claim_b": "the specific claim from PAPER B, one sentence",
  "explanation": "3-5 sentences: how exactly B bears on A, and what remains unsettled",
  "honesty_note": "one sentence on how strong this link really is and what would weaken it",
  "question": "one question the reader could ask to dig further"
}
If not connected, return {"connected": false, "relation": "none"}."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _generate_card_id(key: str) -> str:
    """Same YYYYMMDD_HHMMSS_<hash> shape as digest cards (sorts newest-first)."""
    now = _now()
    short_hash = hashlib.sha256(f"connect:{key}:{now.isoformat()}".encode()).hexdigest()[:8]
    return f"{now.strftime('%Y%m%d_%H%M%S')}_{short_hash}"


def _is_paper_card(card: dict) -> bool:
    return card.get("card_type", "new_paper") in ("new_paper", "")


def _card_summary_text(card: dict) -> str:
    """Hook + gist + key ideas — what we embed and what the LLM sees."""
    digest = card.get("digest") or {}
    if not isinstance(digest, dict):
        digest = {}
    parts = [card.get("hook", ""), digest.get("gist", "")]
    parts.extend(digest.get("key_ideas") or [])
    return "\n".join(p for p in parts if p).strip()


def _library_paper_ids(table, user_id: str, workspace_id: str) -> set[str]:
    """Papers the user has meaningfully engaged with in this workspace."""
    ids: set[str] = set()
    for e in db.list_all_engagement_events(table, user_id, workspace_id):
        pid = e.get("paper_id", "")
        if not pid:
            continue
        action = e.get("action", "")
        if action in LIBRARY_ACTIONS:
            ids.add(pid)
        elif action == "rate" and int(e.get("rating", 0) or 0) >= 4:
            ids.add(pid)
    return ids


def _best_match(hits: list[dict], max_distance: float) -> Optional[dict]:
    """Collapse section-level hits to the closest paper under the threshold.

    Returns {paper_id, paper_title, distance, keys} or None.
    """
    by_paper: dict[str, dict] = {}
    for hit in hits:
        distance = hit.get("distance")
        if distance is None:
            continue
        distance = float(distance)
        if distance > max_distance:
            continue
        meta = hit.get("metadata") or {}
        pid = meta.get("paper_id", "")
        if not pid:
            continue
        entry = by_paper.setdefault(pid, {
            "paper_id": pid,
            "paper_title": meta.get("paper_title", ""),
            "distance": distance,
            "keys": [],
        })
        entry["distance"] = min(entry["distance"], distance)
        entry["keys"].append((distance, hit.get("key", "")))

    if not by_paper:
        return None
    best = min(by_paper.values(), key=lambda e: e["distance"])
    best["keys"] = [k for _, k in sorted(best["keys"])[:2] if k]
    return best


def _build_user_message(
    hypothesis: str,
    old_card: dict,
    old_title: str,
    old_excerpts: list[str],
    pinned: list[dict],
    new_card: dict,
) -> str:
    parts: list[str] = []
    if hypothesis:
        parts.append(f"## Reader's hypothesis\n\n{hypothesis}")

    parts.append(f"## PAPER A (already in the reader's library)\n\nTitle: {old_title or '(unknown)'}")
    old_summary = _card_summary_text(old_card)
    if old_summary:
        parts.append(f"Summary:\n{old_summary}")
    for i, excerpt in enumerate(old_excerpts, 1):
        parts.append(f"Excerpt {i} from PAPER A:\n{excerpt[:1500]}")
    if pinned:
        notes = []
        for turn in pinned[:3]:
            answer = (turn.get("response") or "")[:300]
            if answer:
                note = turn.get("pin_note", "")
                notes.append(f"- {answer}" + (f" (reader's note: {note})" if note else ""))
        if notes:
            parts.append("Insights the reader pinned about PAPER A:\n" + "\n".join(notes))

    parts.append("## PAPER B (arrived today)")
    parts.append(f"Summary:\n{_card_summary_text(new_card)}")
    deep = (new_card.get("digest") or {}).get("deep", "") if isinstance(new_card.get("digest"), dict) else ""
    if deep:
        parts.append(f"Detail:\n{deep[:2500]}")

    parts.append("Is there a specific connection? Return the JSON object.")
    return "\n\n".join(parts)


def _parse_verdict(text: Optional[str]) -> Optional[dict]:
    """Parse the LLM JSON. Returns the verdict only if it is a usable connection."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        cleaned = cleaned.rsplit("```", 1)[0]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        verdict = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        logger.warning("Connect: could not parse LLM verdict")
        return None
    if not isinstance(verdict, dict) or verdict.get("connected") is not True:
        return None
    if verdict.get("relation") not in VALID_RELATIONS:
        return None
    # The gate requires a named claim from each paper, plus something to show.
    for field in ("hook", "claim_a", "claim_b", "explanation"):
        if not str(verdict.get(field) or "").strip():
            return None
    return verdict


def _build_connect_card(new_card: dict, old_card: dict, match: dict, verdict: dict) -> dict:
    new_pid = new_card.get("paper_id", "")
    old_pid = match["paper_id"]
    question = str(verdict.get("question") or "").strip()
    return {
        "card_id": _generate_card_id(f"{new_pid}:{old_pid}"),
        # Anchored to the new paper so "Ask a question" chats over its full text.
        "paper_id": new_pid,
        "source_url": new_card.get("source_url", ""),
        "full_text_s3_key": new_card.get("full_text_s3_key", ""),
        "card_type": "connect",
        "hook": str(verdict["hook"]).strip(),
        "why_you_now": str(verdict.get("why_it_matters") or "").strip(),
        "time_estimate": "2 min",
        "digest": {
            "gist": str(verdict["explanation"]).strip(),
            "key_ideas": [],
            "deep": "",
        },
        "glossary": [],
        "math_notes": [],
        "hypothesis_relevance": "",
        "honesty_note": str(verdict.get("honesty_note") or "").strip(),
        "suggested_questions": [question] if question else [],
        "connection": {
            "relation": verdict["relation"],
            "distance": round(float(match["distance"]), 4),
            "new": {
                "paper_id": new_pid,
                "card_id": new_card.get("card_id", ""),
                "title": new_card.get("hook", ""),
                "claim": str(verdict["claim_b"]).strip(),
            },
            "related": {
                "paper_id": old_pid,
                "card_id": old_card.get("card_id", ""),
                "title": old_card.get("hook", "") or match.get("paper_title", ""),
                "claim": str(verdict["claim_a"]).strip(),
            },
        },
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event: dict, context) -> dict:
    """Lambda handler for the Connect step. Never raises."""
    try:
        return _run(event)
    except Exception:
        logger.exception("Connect step failed — continuing pipeline without connect cards")
        return {"connect_cards": 0, "error": "exception"}


def _run(event: dict) -> dict:
    user_id = event["user_id"]
    workspace_id = event.get("workspace_id", "")
    table_name = event["table_name"]
    model = event.get("model", DEFAULT_MODEL)

    table = boto3.resource("dynamodb").Table(table_name)
    if not workspace_id:
        workspace_id = db.get_active_workspace(table, user_id) or ""

    cards, _ = db.list_feed_cards(table, user_id, workspace_id, limit=50)
    now = _now()

    # Weekly budget + pairs we've already connected.
    week_ago = _iso(now - timedelta(days=7))
    existing_connects = [c for c in cards if c.get("card_type") == "connect"]
    used_this_week = sum(1 for c in existing_connects if (c.get("created_at") or "") >= week_ago)
    budget = min(MAX_PER_RUN, MAX_PER_WEEK - used_this_week)
    if budget <= 0:
        logger.info("Connect: weekly budget spent for %s/%s", user_id, workspace_id)
        return {"connect_cards": 0, "reason": "weekly_cap"}

    seen_pairs = set()
    for c in existing_connects:
        conn = c.get("connection") or {}
        seen_pairs.add((
            (conn.get("new") or {}).get("paper_id", ""),
            (conn.get("related") or {}).get("paper_id", ""),
        ))

    # New full-text paper cards from this run.
    window_start = _iso(now - timedelta(hours=NEW_CARD_WINDOW_HOURS))
    new_cards = [
        c for c in cards
        if _is_paper_card(c)
        and (c.get("created_at") or "") >= window_start
        and c.get("content_basis", "full_text") != "abstract"
        and _card_summary_text(c)
    ]
    if not new_cards:
        return {"connect_cards": 0, "reason": "no_new_cards"}

    new_paper_ids = {c.get("paper_id", "") for c in new_cards}
    library_ids = _library_paper_ids(table, user_id, workspace_id) - new_paper_ids
    if not library_ids:
        logger.info("Connect: no engaged papers yet for %s/%s", user_id, workspace_id)
        return {"connect_cards": 0, "reason": "empty_library"}

    from backend.shared.embeddings import embed_text
    from backend.shared.vectors import get_chunk_texts, query_vectors

    # 1. Vector prefilter: closest engaged paper for each new card.
    candidates: list[tuple[dict, dict]] = []
    for card in new_cards:
        try:
            embedding = embed_text(_card_summary_text(card))
        except Exception:
            logger.warning("Connect: embedding failed for card %s", card.get("card_id", ""))
            continue
        hits = query_vectors(embedding, paper_ids=library_ids, top_k=8, return_distance=True)
        match = _best_match(hits, MAX_DISTANCE)
        if match and (card.get("paper_id", ""), match["paper_id"]) not in seen_pairs:
            candidates.append((card, match))

    if not candidates:
        return {"connect_cards": 0, "reason": "no_close_match"}
    candidates.sort(key=lambda pair: pair[1]["distance"])

    profile = db.get_full_profile(table, user_id, workspace_id)
    hypothesis = ((profile.get("hypothesis") or {}).get("statement") or "").strip()

    # 2. LLM gate, closest pair first.
    written = 0
    attempts = 0
    for new_card, match in candidates:
        if written >= budget or attempts >= MAX_LLM_ATTEMPTS:
            break
        attempts += 1
        old_pid = match["paper_id"]
        old_card = db.get_feed_card_by_paper(table, user_id, workspace_id, old_pid) or {}
        chunk_texts = get_chunk_texts({old_pid})
        excerpts = [chunk_texts[k] for k in match["keys"] if chunk_texts.get(k)]
        if not excerpts and not _card_summary_text(old_card):
            continue  # nothing concrete about paper A to reason over
        pinned = db.get_pinned_turns(table, user_id, workspace_id, old_pid)

        response = call_llm_with_fallback(
            system=SYSTEM_PROMPT,
            user_message=_build_user_message(
                hypothesis, old_card, match.get("paper_title", ""), excerpts, pinned, new_card,
            ),
            primary_model=model,
            fallback_model=FALLBACK_MODEL,
            max_tokens=800,
            temperature=0.2,
        )
        verdict = _parse_verdict(response)
        if not verdict:
            logger.info(
                "Connect: gate rejected %s ↔ %s (distance=%.3f)",
                new_card.get("paper_id", ""), old_pid, match["distance"],
            )
            continue

        connect_card = _build_connect_card(new_card, old_card, match, verdict)
        db.put_feed_card(table, user_id, workspace_id, connect_card)
        written += 1
        logger.info(
            "Connect card written: %s (%s %s %s)",
            connect_card["card_id"], new_card.get("paper_id", ""), verdict["relation"], old_pid,
        )

    metrics.emit("ConnectCardsGenerated", written)
    return {"connect_cards": written, "candidates": len(candidates), "llm_attempts": attempts}

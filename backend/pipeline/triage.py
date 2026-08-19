"""Pipeline step: Triage candidate papers using LLM."""

from __future__ import annotations

import json
import logging
import os

import boto3

from backend.shared import db
from backend.shared.llm import call_llm, call_llm_with_fallback

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_MODEL = os.environ.get("TRIAGE_MODEL", "moonshotai.kimi-k2.5")
FALLBACK_MODEL = "us.anthropic.claude-sonnet-4-6"


def _build_system_prompt() -> str:
    return (
        "You are a research paper triage agent. "
        "Score this paper for a specific user based on their learner profile. "
        "The user is a practitioner who builds things but has little academic vocabulary. "
        "They care about applied relevance to what they are building, not comprehension for its own sake.\n\n"
        "You must respond with ONLY valid JSON (no markdown fencing, no extra text) with these fields:\n"
        "- triage_score: float 0-1 (overall score combining relevance, level fit, and hypothesis alignment)\n"
        '- level: one of "too_basic", "just_right", "over_head"\n'
        "- hypothesis_relevant: boolean (true if paper relates to the hypothesis)\n"
        "- reasoning: string (1-2 sentences explaining the score)\n"
        "- worth_my_hours: boolean (true if this paper is worth the user's limited reading time)\n"
    )


def _stringify(v) -> str:
    """Flatten a profile field that may be a str or a dict into a compact string."""
    if isinstance(v, dict):
        return "; ".join(f"{k}: {val}" for k, val in v.items() if val)
    return str(v or "").strip()


def _build_user_message(paper: dict, profile: dict) -> str:
    """Construct the user message with paper and profile context."""
    # Extract areas info (incl. per-area level + intent, which drive scoring)
    areas_text = ""
    for area in profile.get("areas", []):
        label = area.get("label", "unknown")
        frontier = area.get("frontier", "")
        too_basic = area.get("too_basic", [])
        just_right = area.get("just_right", [])
        role = area.get("role", "")
        level = area.get("current_level", "intermediate")
        intent = area.get("intent", "consume")
        areas_text += (
            f"- {label} (role: {role}, level: {level}, intent: {intent})\n"
            f"  Frontier: {frontier}\n"
            f"  Too basic: {too_basic}\n"
            f"  Just right: {just_right}\n"
        )

    # Extract hypothesis
    hypothesis_item = profile.get("hypothesis")
    hypothesis_statement = ""
    if hypothesis_item:
        hypothesis_statement = hypothesis_item.get(
            "statement",
            "Brain-structure + agentic harness >> the LLM.",
        )

    # User-level context, from THIS user's profile (falls back to neutral
    # phrasing when a field is unset — never assumes a specific persona).
    um = profile.get("user_meta", {}) or {}
    background = str(um.get("background", "") or "").strip()
    learning_style = _stringify(um.get("learning_style", ""))
    math_comfort = str(um.get("math_comfort", "") or "").strip()
    paper_preference = _stringify(um.get("paper_preference", ""))
    time_per_week = str(um.get("time_per_week", "") or "").strip()
    trusted = (profile.get("meta", {}) or {}).get("trusted_venues", []) or []

    ctx_lines = []
    if background:
        ctx_lines.append(f"Background: {background}")
    if learning_style:
        ctx_lines.append(f"Learning style: {learning_style}")
    if math_comfort:
        ctx_lines.append(f"Math comfort: {math_comfort}")
    if paper_preference:
        ctx_lines.append(f"Paper preference: {paper_preference}")
    if time_per_week:
        ctx_lines.append(f"Reading time per week: {time_per_week}")
    if trusted:
        ctx_lines.append(f"Trusted venues/authors: {', '.join(map(str, trusted))}")
    context_block = "\n".join(ctx_lines) if ctx_lines else "No additional profile context provided."

    # Paper info
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    authors = paper.get("authors", [])
    areas_matched = paper.get("areas_matched", [])

    message = (
        "## Paper to Triage\n\n"
        f"**Title:** {title}\n"
        f"**Authors:** {', '.join(authors) if authors else 'Unknown'}\n"
        f"**Areas matched during discovery:** {', '.join(areas_matched) if areas_matched else 'None'}\n\n"
        f"**Abstract:**\n{abstract}\n\n"
        "## User Profile\n\n"
        "### Research Areas (with level + intent)\n"
        f"{areas_text}\n"
        "### Hypothesis\n"
        f"{hypothesis_statement or 'None stated.'}\n\n"
        "### About this user\n"
        f"{context_block}\n\n"
        "## Instructions\n\n"
        "Score this paper FOR THIS USER using the profile above:\n"
        "1. Relevance to their areas (0-1). Papers at intersections of their areas are highest value.\n"
        "2. Right level? Judge against each area's stated level and the user's math comfort: "
        "too_basic = below what they already know; just_right = stretches them at their level; "
        "over_head = demands background/math beyond their comfort.\n"
        "3. Intent fit: for a 'consume' area favor accessible, foundational, or survey/tutorial work; "
        "for a 'produce' area favor novel methods, frontier results, and reproducible/implementable work.\n"
        "4. Hypothesis relevance, if a hypothesis is stated.\n"
        "5. Overall triage_score (0-1, combining relevance, level, intent, hypothesis).\n"
        "6. Brief reasoning (1-2 sentences).\n"
        "7. worth_my_hours: given their weekly reading time, is this worth it?\n\n"
        "Respond with ONLY the JSON object."
    )
    return message


def _score_paper(model: str, paper: dict, profile: dict) -> dict:
    """Call the LLM to score a single paper against the user's profile.

    Returns a dict with triage_score, level, hypothesis_relevant, reasoning, worth_my_hours.
    On failure, returns a zeroed-out result.
    """
    try:
        text = call_llm_with_fallback(
            system=_build_system_prompt(),
            user_message=_build_user_message(paper, profile),
            primary_model=model,
            fallback_model=FALLBACK_MODEL,
            max_tokens=500,
        )

        if text is None:
            logger.error(
                "LLM call returned None for paper %s",
                paper.get("id", "unknown"),
            )
            return {
                "triage_score": 0.0,
                "level": "just_right",
                "hypothesis_relevant": False,
                "reasoning": "LLM triage failed — API error.",
                "worth_my_hours": False,
            }

        # Strip and try to parse JSON, stripping markdown fences if present
        text = text.strip()
        if text.startswith("```"):
            # Remove ```json or ``` prefix and trailing ```
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        result = json.loads(text)

        # Validate required fields
        triage_score = float(result.get("triage_score", 0))
        triage_score = max(0.0, min(1.0, triage_score))

        level = result.get("level", "just_right")
        if level not in ("too_basic", "just_right", "over_head"):
            level = "just_right"

        return {
            "triage_score": triage_score,
            "level": level,
            "hypothesis_relevant": bool(result.get("hypothesis_relevant", False)),
            "reasoning": str(result.get("reasoning", "")),
            "worth_my_hours": bool(result.get("worth_my_hours", False)),
        }

    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        logger.warning(
            "Failed to parse LLM triage response for paper %s: %s",
            paper.get("id", "unknown"),
            str(e),
        )
        return {
            "triage_score": 0.0,
            "level": "just_right",
            "hypothesis_relevant": False,
            "reasoning": "LLM triage failed — could not parse response.",
            "worth_my_hours": False,
        }


def handler(event: dict, context) -> dict:
    """Lambda handler for the Triage step.

    Reads candidate papers + profile from DDB. LLM scores each paper's
    abstract against the profile (relevance, level, hypothesis fit).
    Updates triage_score and triage_reasoning on each paper record.

    Event:
        user_id: str — the user to triage papers for
        table_name: str — DynamoDB table name
        model: str (optional) — Anthropic model to use, default claude-sonnet-4-20250514
    """
    user_id = event["user_id"]
    workspace_id = event.get("workspace_id", "")
    table_name = event["table_name"]
    model = event.get("model", DEFAULT_MODEL)

    # Set up DynamoDB table resource
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    if not workspace_id:
        workspace_id = db.get_active_workspace(table, user_id) or ""

    # 1. Load user profile (workspace areas/hypothesis + user-level META, so
    # scoring reflects THIS user's background/learning style/math comfort — not
    # a hard-coded persona).
    profile = db.get_full_profile(table, user_id, workspace_id)
    if not profile.get("areas") and not profile.get("hypothesis"):
        logger.warning("No profile found for user %s ws %s — skipping triage.", user_id, workspace_id)
        return {"papers_triaged": 0, "worth_reading": 0}
    profile["user_meta"] = db.get_user_meta(table, user_id) or {}

    # 2. Load candidate papers
    candidates = db.list_papers_by_status(table, user_id, workspace_id, "candidate", limit=100)
    if not candidates:
        logger.info("No candidate papers to triage for user %s.", user_id)
        return {"papers_triaged": 0, "worth_reading": 0}

    # 3. Score each paper and update DDB
    papers_triaged = 0
    worth_reading = 0

    for paper in candidates:
        paper_id = paper.get("id")
        if not paper_id:
            logger.warning("Candidate paper missing 'id' field, skipping.")
            continue

        logger.info("Triaging paper: %s (%s)", paper_id, paper.get("title", "untitled"))

        score_result = _score_paper(model, paper, profile)

        # Update the paper record with triage results
        paper["triage_score"] = score_result["triage_score"]
        paper["triage_reasoning"] = score_result["reasoning"]
        paper["worth_my_hours"] = score_result["worth_my_hours"]
        paper["triage_level"] = score_result["level"]
        paper["hypothesis_relevant"] = score_result["hypothesis_relevant"]

        # Move status to "surfaced" if worth reading, keep as "candidate" otherwise
        if score_result["worth_my_hours"]:
            paper["status"] = "surfaced"
            worth_reading += 1

        db.put_paper(table, user_id, workspace_id, paper)
        papers_triaged += 1

    logger.info(
        "Triage complete for user %s: %d triaged, %d worth reading.",
        user_id,
        papers_triaged,
        worth_reading,
    )

    from backend.shared import metrics
    metrics.emit("PapersTriaged", papers_triaged)
    metrics.emit("PapersWorthReading", worth_reading)

    return {"papers_triaged": papers_triaged, "worth_reading": worth_reading}

"""Pipeline step: Triage candidate papers using LLM."""

from __future__ import annotations

import json
import logging

import boto3

from backend.shared import db
from backend.shared.llm import call_llm

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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


def _build_user_message(paper: dict, profile: dict) -> str:
    """Construct the user message with paper and profile context."""
    # Extract areas info
    areas_text = ""
    for area in profile.get("areas", []):
        label = area.get("label", "unknown")
        frontier = area.get("frontier", "")
        too_basic = area.get("too_basic", [])
        just_right = area.get("just_right", [])
        role = area.get("role", "")
        areas_text += (
            f"- {label} (role: {role})\n"
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
        "### Research Areas\n"
        f"{areas_text}\n"
        "### Hypothesis\n"
        f"{hypothesis_statement}\n\n"
        "### Context\n"
        "The user is a practitioner-builder with zero academic vocabulary. "
        "They have never read a paper end-to-end. Math is opaque to them. "
        "They want papers that connect to what they are building (a faithful AI clone of a person "
        "using memory architecture and agentic harness). "
        "Papers at intersections of their areas are highest value. "
        "The hypothesis to pressure-test: the right brain-structure + harness matters more than the LLM itself.\n\n"
        "## Instructions\n\n"
        "Score this paper:\n"
        "1. How relevant is it to the user's areas? (0-1)\n"
        "2. Is this at the right level? (too_basic = things they already know; "
        "just_right = stretches them without requiring math; over_head = heavy math/theory they can't parse)\n"
        "3. Is this relevant to their hypothesis (brain-structure + harness >> LLM)?\n"
        "4. Overall triage_score (0-1, combining relevance, level, hypothesis)\n"
        "5. Brief reasoning (1-2 sentences)\n"
        "6. worth_my_hours: given they have 2-4 hrs/week total, is this worth their time?\n\n"
        "Respond with ONLY the JSON object."
    )
    return message


def _score_paper(model: str, paper: dict, profile: dict) -> dict:
    """Call the LLM to score a single paper against the user's profile.

    Returns a dict with triage_score, level, hypothesis_relevant, reasoning, worth_my_hours.
    On failure, returns a zeroed-out result.
    """
    try:
        text = call_llm(
            system=_build_system_prompt(),
            user_message=_build_user_message(paper, profile),
            model_id=model,
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
    table_name = event["table_name"]
    model = event.get("model", "us.anthropic.claude-sonnet-4-6")

    # Set up DynamoDB table resource
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # 1. Load user profile
    profile = db.get_full_profile(table, user_id)
    if not profile.get("areas") and not profile.get("hypothesis"):
        logger.warning("No profile found for user %s — skipping triage.", user_id)
        return {"papers_triaged": 0, "worth_reading": 0}

    # 2. Load candidate papers
    candidates = db.list_papers_by_status(table, user_id, "candidate", limit=100)
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

        db.put_paper(table, user_id, paper)
        papers_triaged += 1

    logger.info(
        "Triage complete for user %s: %d triaged, %d worth reading.",
        user_id,
        papers_triaged,
        worth_reading,
    )

    return {"papers_triaged": papers_triaged, "worth_reading": worth_reading}

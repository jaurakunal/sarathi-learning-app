"""Onboarding chat handler — LLM-driven interview to build a user profile.

The conversation continues until the LLM reaches high confidence it understands
the user's background, goals, areas, and level. Then it generates a structured
profile and returns it for confirmation.
"""

from __future__ import annotations

import json
import logging
import os

import boto3

from backend.shared import db
from backend.shared.llm import call_llm_multi

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")

ONBOARDING_SYSTEM_PROMPT = """You are Sārathi's onboarding assistant. Your job is to deeply understand a new user so we can personalize their research paper feed.

You need to understand:
1. WHO they are — role, background, what they build day-to-day
2. WHAT they want from Sārathi — learning goals, research interests, what kind of papers they want to see
3. Their AREAS of interest — specific topics (2-5 areas), for each: what they already know vs. what they want to learn
4. Their LEVEL — for each area, are they a beginner exploring, a practitioner building, or an expert pushing frontiers?
5. Their GOAL — is there a thesis, project, or question driving their research? What would "success" look like?
6. Their STYLE — do they prefer math-heavy papers, applied/code-focused, survey overviews, or specific conferences?

RULES:
- Ask one focused question at a time. Don't overwhelm with multi-part questions.
- Follow up on their answers — go deep. If they say "I'm interested in AI agents", ask WHAT about agents, WHAT they've built, WHAT they struggle with.
- Use their language back to them — don't impose jargon they haven't used.
- Be warm but efficient. This isn't a casual chat — it's a focused interview.
- After each answer, decide if you need to dig deeper on that topic or move to the next.
- Track your confidence internally. You need high confidence on ALL 6 dimensions above.

WHEN YOU'RE DONE (all 6 dimensions at high confidence):
- Respond with a JSON block wrapped in ```json fences containing:
  {
    "type": "profile_complete",
    "confidence": 0.9+,
    "summary": "2-3 sentence natural language summary of who they are",
    "profile": {
      "areas": [{"id": "slug", "label": "Display Name", "role": "primary|secondary", "frontier": "what they want to learn here", "current_level": "beginner|intermediate|advanced"}],
      "meta": {
        "learning_style": {"depth": "practitioner|theorist|hybrid", "math_comfort": "avoid|tolerate|enjoy", "paper_preference": "applied|theoretical|survey"},
        "paper_goal": "what they want from reading papers",
        "background": "1-2 sentence professional context"
      },
      "hypothesis": {"statement": "their driving research question or thesis, if any", "status": "forming|testing|refining"}
    }
  }

IMPORTANT: Only output the JSON when you are genuinely confident (>90%). Do NOT rush. Better to ask one more question than to get the profile wrong. The user will confirm or correct your summary."""

CONTINUE_SYSTEM_PROMPT = """You are continuing an onboarding interview for Sārathi. Review the conversation history and continue from where you left off. Remember the rules: ask one focused question at a time, go deep, track your confidence across all 6 dimensions (who, what, areas, level, goal, style).

If you now have enough information (>90% confidence on all dimensions), output the profile JSON as specified."""


def _get_user_id(event: dict) -> str:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    return claims.get("sub", "")


def handler(event: dict, context) -> dict:
    """
    POST /onboarding — send a message in the onboarding conversation
    GET /onboarding — check onboarding status (has profile or not)
    """
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    method = event.get("httpMethod", "")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    if method == "GET":
        profile = db.get_full_profile(table, user_id)
        has_profile = bool(profile.get("meta"))
        return _response(200, {"has_profile": has_profile})

    if method != "POST":
        return _response(405, {"error": "Method not allowed"})

    body = json.loads(event.get("body") or "{}")
    message = body.get("message", "").strip()

    # Get or create onboarding conversation
    conv_id = "onboarding"
    conv = db.get_conversation_by_paper(table, user_id, conv_id)
    if conv is None:
        db.create_conversation(table, user_id, conv_id, "")
        conv = {"conv_id": conv_id}

    # Get conversation history
    turns = db.get_conversation_turns(table, user_id, conv_id)

    # Build messages for LLM
    llm_messages = []
    for turn in turns:
        if turn.get("request"):
            llm_messages.append({"role": "user", "content": turn["request"]})
        if turn.get("response"):
            llm_messages.append({"role": "assistant", "content": turn["response"]})

    # Add current message
    if message:
        llm_messages.append({"role": "user", "content": message})

    # Determine system prompt
    system = ONBOARDING_SYSTEM_PROMPT if len(turns) == 0 else CONTINUE_SYSTEM_PROMPT

    # If this is the very first message and it's empty, generate the opening question
    if not message and len(turns) == 0:
        llm_messages.append({"role": "user", "content": "Hi, I just signed up."})

    # Call LLM
    response = call_llm_multi(
        system=system,
        messages=llm_messages,
        model_id="us.anthropic.claude-sonnet-4-6",
        max_tokens=1500,
        temperature=0.4,
    )

    if not response:
        return _response(500, {"error": "LLM call failed"})

    # Save the turn
    seq = len(turns) + 1
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    user_msg = message or "Hi, I just signed up."
    db.put_turn(table, user_id, conv_id, seq, user_msg, ts)
    db.update_turn_response(table, user_id, conv_id, seq, response, ts, [], 0, 0)
    db.update_conversation_last_active(table, user_id, conv_id)

    # Check if the response contains a profile_complete JSON
    profile_data = _extract_profile(response)

    result: dict = {"response": response, "turn_seq": seq}

    if profile_data:
        result["profile_complete"] = True
        result["profile_summary"] = profile_data.get("summary", "")
        result["profile"] = profile_data.get("profile", {})

    return _response(200, result)


def _extract_profile(response: str) -> dict | None:
    """Try to extract profile_complete JSON from the LLM response."""
    if "profile_complete" not in response:
        return None

    try:
        # Find JSON block in markdown fences
        start = response.find("```json")
        if start == -1:
            start = response.find("```")
        if start == -1:
            return None

        start = response.index("\n", start) + 1
        end = response.find("```", start)
        if end == -1:
            return None

        json_str = response[start:end].strip()
        data = json.loads(json_str)

        if data.get("type") == "profile_complete" and data.get("profile"):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }

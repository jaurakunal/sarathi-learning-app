"""API handler for generating chat question suggestions."""

from __future__ import annotations

import json
import logging
import os

import boto3

from backend.shared import db
from backend.shared.llm import call_llm
from backend.api._workspace_helper import get_user_id as _get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")

SUGGEST_PROMPT = """You generate follow-up questions for a research reader.

Given:
- The conversation so far (last few turns)
- The user's research profile (areas, hypothesis, level)
- The paper context

Generate exactly 3 short follow-up questions (max 12 words each) that:
1. Dig deeper into what was just discussed
2. Connect to the user's research goals
3. Push toward synthesis or application

The questions should feel like what a curious practitioner would naturally ask next — not generic. They should be specific to this conversation and this user.

Return ONLY a JSON array of 3 strings. No explanation, no markdown."""


def handler(event: dict, context) -> dict:
    """POST /suggest — generate follow-up question suggestions."""
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Invalid JSON"})

    paper_id = body.get("paper_id", "")
    if not paper_id:
        return _response(400, {"error": "paper_id required"})

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    # Get last few conversation turns
    turns = db.get_conversation_turns(table, user_id, workspace_id, paper_id)
    recent_turns = turns[-4:]  # Last 2 exchanges

    # Get user profile (compact)
    profile = db.get_full_profile(table, user_id, workspace_id)
    areas = profile.get("areas", [])
    hypothesis = profile.get("hypothesis", {})

    # Build context for suggestion generation
    conv_context = ""
    for turn in recent_turns:
        if turn.get("request"):
            conv_context += f"User: {turn['request'][:200]}\n"
        if turn.get("response"):
            conv_context += f"Assistant: {turn['response'][:300]}\n"

    profile_context = ""
    if areas:
        profile_context += "Research areas: " + ", ".join(a.get("label", "") for a in areas[:4]) + "\n"
    if hypothesis and hypothesis.get("statement"):
        profile_context += f"Thesis: {hypothesis['statement'][:200]}\n"

    user_msg = f"""CONVERSATION SO FAR:
{conv_context}

USER PROFILE:
{profile_context}

Generate 3 follow-up questions."""

    try:
        response = call_llm(
            system=SUGGEST_PROMPT,
            user_message=user_msg,
            model_id="us.anthropic.claude-haiku-4-5-20251001",
            max_tokens=200,
            temperature=0.7,
        )

        if response:
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            suggestions = json.loads(text.strip())
            if isinstance(suggestions, list):
                return _response(200, {"suggestions": suggestions[:3]})
    except Exception:
        logger.exception("Failed to generate suggestions")

    return _response(200, {"suggestions": []})


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
        },
        "body": json.dumps(body),
    }

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

ONBOARDING_SYSTEM_PROMPT = """You are Sārathi's onboarding assistant. Your job is to DEEPLY understand a new user so we can personalize their research paper feed at exactly the right level — not too basic, not too advanced.

You need to understand these dimensions. Do NOT declare confidence until you've probed each one thoroughly:

1. WHO they are — role, years of experience, what they build/research day-to-day.

2. AREAS of interest (2-5 areas) — for EACH area, you must know:
   a) What specifically interests them (not just "AI agents" but "memory persistence for multi-session agents")
   b) What they've already built or read in this area (establishes their floor)
   c) What concepts/terms they're comfortable with vs. what's new to them
   d) Where they want to go (their frontier — what they want to understand next)

3. CALIBRATION PER AREA — this is critical. For each area, probe with concrete questions:
   - "Have you implemented X before, or just read about it?"
   - "When you hear [specific technical term], does that mean something to you or is it new?"
   - "What's the most recent paper/blog/project you engaged with in this area?"
   - "If I showed you a paper on [specific subtopic], would you understand the motivation or need background?"
   Use their answers to determine: beginner (needs fundamentals explained), intermediate (knows concepts, building understanding), or advanced (pushing frontiers, wants cutting-edge).

4. WHAT THEY'VE ALREADY CONSUMED — papers they've read, courses taken, projects built. This tells us what's too basic for them. A paper recommender that suggests things they already know is useless.

5. MATH & THEORY COMFORT — not just "avoid/tolerate/enjoy" broadly, but per area:
   - They might be fine with systems math (complexity, graphs) but lost on ML math (gradients, attention)
   - Probe with examples: "If a paper has equations for loss functions, do you skip that section?"

6. GOAL — what's driving their research? A project? A thesis? Career growth? Curiosity? What would "success" look like in 3 months?

7. STYLE — reading pace, preferred paper length, whether they want surveys/tutorials or only novel results, whether they want code implementations.

RULES:
- Ask ONE focused question at a time. Never multi-part.
- Follow up relentlessly — "interesting, tell me more about..." — don't accept surface answers.
- For each area they mention, ask at least 2-3 calibration probes before moving on.
- Use THEIR language. If they say "embeddings", don't switch to "dense vector representations".
- Do NOT rush to finish. A 12-15 turn conversation is expected and appropriate.
- Track confidence per dimension internally. You need >90% on ALL dimensions.
- If someone gives a vague answer ("I'm interested in LLMs"), drill down: "What ABOUT LLMs? Training them? Using them? Evaluating them? The architecture itself?"

WHEN YOU'RE DONE (genuinely >90% on all dimensions — typically turn 12+):
- First, give a natural language summary of what you understood
- Then output a JSON block wrapped in ```json fences:
  {
    "type": "profile_complete",
    "confidence": 0.92,
    "summary": "2-3 sentence summary",
    "profile": {
      "areas": [
        {
          "id": "slug",
          "label": "Display Name",
          "role": "primary|secondary",
          "frontier": "specific thing they want to learn next",
          "current_level": "beginner|intermediate|advanced",
          "knows": ["concepts/terms they're comfortable with"],
          "too_basic": ["things that would be too elementary for them"]
        }
      ],
      "meta": {
        "learning_style": {"depth": "practitioner|theorist|hybrid", "math_comfort": "avoid|tolerate|enjoy", "paper_preference": "applied|theoretical|survey"},
        "paper_goal": "what they want from reading papers",
        "background": "1-2 sentence professional context"
      },
      "hypothesis": {"statement": "their driving research question or thesis, if any", "status": "forming|testing|refining"}
    }
  }

CRITICAL: Do NOT output JSON before turn 10 at minimum. If you find yourself ready at turn 6, you haven't probed deeply enough. Go back and calibrate each area with specific technical questions."""

CONTINUE_SYSTEM_PROMPT = """You are continuing an onboarding interview for Sārathi. Review the conversation history and continue where you left off.

Remember:
- Ask ONE focused question at a time
- You need per-area calibration (what they know, what's new, what's too basic)
- Don't rush — 12-15 turns is normal and expected
- If you haven't probed each area with 2-3 calibration questions, you're not done
- Only output profile JSON when genuinely >90% confident on ALL dimensions

If you now have enough information (all areas calibrated, all dimensions covered), output the profile JSON."""


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
        max_tokens=24000,
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
    """Try to extract a profile JSON from the LLM response.

    Handles multiple formats:
    - Prescribed format: {type: "profile_complete", profile: {...}}
    - Free-form: {who: {...}, areas: {...}, level: {...}, goal: {...}}
    - With or without markdown fences
    """
    # Try to find JSON in the response — either in fences or bare
    json_str = None

    # Check for markdown fences first
    fence_start = response.find("```json")
    if fence_start == -1:
        fence_start = response.find("```")
    if fence_start != -1:
        try:
            content_start = response.index("\n", fence_start) + 1
            fence_end = response.find("```", content_start)
            if fence_end != -1:
                json_str = response[content_start:fence_end].strip()
        except ValueError:
            pass

    # If no fences, look for a bare JSON object (starts with { on its own line)
    if not json_str:
        lines = response.split("\n")
        brace_start = None
        for i, line in enumerate(lines):
            if line.strip() == "{":
                brace_start = i
                break
            elif line.strip().startswith('{"'):
                brace_start = i
                break
        if brace_start is not None:
            remaining = "\n".join(lines[brace_start:])
            depth = 0
            end_idx = 0
            for idx, ch in enumerate(remaining):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = idx + 1
                        break
            if end_idx > 0:
                json_str = remaining[:end_idx]

    if not json_str:
        return None

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    # Handle prescribed format
    if data.get("type") == "profile_complete" and data.get("profile"):
        return data

    # Handle free-form format (has keys like who, areas, level, goal)
    if any(k in data for k in ("areas", "level", "goal", "who", "what")):
        profile = _normalize_freeform_profile(data)
        summary = _build_summary_from_profile(data)
        return {
            "type": "profile_complete",
            "confidence": data.get("level", {}).get("confidence", 90) if isinstance(data.get("level"), dict) else 90,
            "summary": summary,
            "profile": profile,
        }

    return None


def _normalize_freeform_profile(data: dict) -> dict:
    """Convert a free-form LLM profile JSON into the structured format we store."""
    areas_raw = data.get("areas", {})
    who = data.get("who", {})
    level = data.get("level", {})
    goal = data.get("goal", {})
    style = data.get("style", {})
    what = data.get("what", {})

    # Build areas list — LLM uses various key names for primary/secondary
    areas = []
    if isinstance(areas_raw, dict):
        core_areas = areas_raw.get("core", []) or areas_raw.get("primary", []) or []
        adjacent_areas = areas_raw.get("adjacent", []) or areas_raw.get("secondary", []) or []
    elif isinstance(areas_raw, list):
        core_areas = areas_raw
        adjacent_areas = []
    else:
        core_areas = []
        adjacent_areas = []

    for label in core_areas:
        if isinstance(label, dict):
            areas.append({
                "id": label.get("id", label.get("label", "")[:30].lower().replace(" ", "-")),
                "label": label.get("label", ""),
                "role": "primary",
                "frontier": label.get("frontier", ""),
                "current_level": label.get("current_level", "intermediate"),
                "knows": label.get("knows", []),
                "too_basic": label.get("too_basic", []),
            })
        else:
            areas.append({
                "id": str(label).lower().replace(" ", "-").replace("&", "and").replace("(", "").replace(")", "")[:30],
                "label": str(label),
                "role": "primary",
                "frontier": "",
                "current_level": level.get("ml_ai_theory", "intermediate") if isinstance(level, dict) else "intermediate",
            })
    for label in adjacent_areas:
        if isinstance(label, dict):
            areas.append({
                "id": label.get("id", label.get("label", "")[:30].lower().replace(" ", "-")),
                "label": label.get("label", ""),
                "role": "secondary",
                "frontier": label.get("frontier", ""),
                "current_level": label.get("current_level", "beginner"),
                "knows": label.get("knows", []),
                "too_basic": label.get("too_basic", []),
            })
        else:
            areas.append({
                "id": str(label).lower().replace(" ", "-").replace("&", "and").replace("(", "").replace(")", "")[:30],
                "label": str(label),
                "role": "secondary",
                "frontier": "",
                "current_level": "beginner",
            })

    # Build meta
    meta = {
        "learning_style": {
            "depth": "practitioner",
            "math_comfort": "avoid" if "avoid" in str(style).lower() or "math" in str(style).lower() else "tolerate",
            "paper_preference": "applied",
        },
        "paper_goal": goal.get("primary", "") if isinstance(goal, dict) else str(goal),
        "background": f"{who.get('role', '')} — {who.get('domain', '')}" if isinstance(who, dict) else "",
    }

    # Hypothesis
    hypothesis = {
        "statement": goal.get("primary", "") if isinstance(goal, dict) else "",
        "status": "forming",
    }

    return {"areas": areas, "meta": meta, "hypothesis": hypothesis}


def _build_summary_from_profile(data: dict) -> str:
    """Build a natural-language summary from the free-form profile data."""
    who = data.get("who", {})
    goal = data.get("goal", {})
    areas = data.get("areas", {})

    parts = []
    if isinstance(who, dict) and who.get("role"):
        parts.append(f"{who['role']} working in {who.get('domain', 'tech')}")
    if isinstance(areas, dict) and areas.get("core"):
        parts.append(f"focused on {', '.join(areas['core'][:3])}")
    if isinstance(goal, dict) and goal.get("primary"):
        parts.append(f"with the goal of: {goal['primary']}")

    return ". ".join(parts) + "." if parts else "Profile built from onboarding interview."


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

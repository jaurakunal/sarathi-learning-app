"""Onboarding chat handler — two-stage LLM-driven interview.

Stage 1 (user-level, ~5-7 turns): collects WHO the user is — background,
learning_style, math_comfort, paper_preference, time_per_week. This runs
ONCE per user. Once done, we set USER#<sub>#ONBOARDING SK=META.

Stage 2 (workspace-level, ~12-15 turns): collects WHAT they want from this
workspace — areas, hypothesis, paper_goal, frontier_per_area. Runs once per
workspace.

GET  /onboarding         — return status: which stage to run
POST /onboarding         — send a message; ?stage=user|workspace selects stage.
                           Falls back to user stage if user-level META missing,
                           else workspace stage. The workspace stage requires
                           ?workspace_id=<wid> (or active workspace pointer).
"""

from __future__ import annotations

import json
import logging
import os

import boto3

from backend.shared import db
from backend.shared.llm import call_llm_multi
from backend.api._workspace_helper import get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


# ---------------------------------------------------------------------------
# Stage 1: user-level (background, learning_style, math_comfort, etc.)
# ---------------------------------------------------------------------------

USER_LEVEL_SYSTEM_PROMPT = """You are Sārathi's user-level onboarding assistant. Your job is to understand WHO this person is so we can calibrate ALL of their workspaces.

This is a SHORT conversation (5-7 turns). Focus only on traits that travel with the user across every research area:

1. WHO they are — role, years of experience, what they build day-to-day.
2. LEARNING STYLE — practitioner vs theorist? Routes-around math vs digs in?
3. MATH & THEORY COMFORT — avoid / tolerate / enjoy. Probe with one concrete example: "When a paper has equations for loss functions, do you skip that section?"
4. PAPER PREFERENCE — applied / theoretical / survey / mixed.
5. TIME — how many hours/week can they realistically spend reading research?

RULES:
- Ask ONE focused question at a time.
- Keep it tight — 5-7 turns. This is NOT the area-specific deep dive (that comes next per-workspace).
- Use their language.

WHEN YOU'RE DONE (typically turn 5-7):
- Give a 1-2 sentence summary of what you understood.
- Then output a JSON block in ```json fences:
  {
    "type": "user_meta_complete",
    "summary": "1-2 sentence summary",
    "user_meta": {
      "background": "1-2 sentence professional context",
      "learning_style": {"depth": "practitioner|theorist|hybrid"},
      "math_comfort": "avoid|tolerate|enjoy",
      "paper_preference": "applied|theoretical|survey|mixed",
      "time_per_week": "<hours, e.g. 2-4>"
    }
  }
"""

USER_LEVEL_CONTINUE_PROMPT = """Continue the user-level onboarding interview. Stay focused on user-level traits (background, learning_style, math_comfort, paper_preference, time_per_week). Ask ONE question at a time. When you have enough (typically turn 5-7), output the user_meta_complete JSON."""


# ---------------------------------------------------------------------------
# Stage 2: workspace-level (areas, hypothesis, paper_goal, frontier)
# ---------------------------------------------------------------------------

WORKSPACE_LEVEL_SYSTEM_PROMPT = """You are Sārathi's workspace-level onboarding assistant. The user has already told us WHO they are — your job now is to understand what THIS particular workspace is for. A user can have multiple workspaces (e.g., one for AI agents, one for security, etc.) — focus tightly on the topic of THIS one.

You need to understand these dimensions deeply (>90% confidence each):

1. AREAS of interest in this workspace (2-5 areas). For EACH area, you must know:
   a) What specifically interests them (not just "AI agents" but "memory persistence for multi-session agents")
   b) What they've already built or read in this area (establishes their floor)
   c) What concepts/terms they're comfortable with vs. what's new to them
   d) Where they want to go (their frontier — what they want to understand next)

2. CALIBRATION PER AREA — concrete probes:
   - "Have you implemented X before, or just read about it?"
   - "When you hear [specific technical term], does that mean something to you or is it new?"
   - "What's the most recent paper/blog/project you engaged with in this area?"

3. WHAT THEY'VE ALREADY CONSUMED — papers they've read, projects built. This tells us what's too basic for them in this workspace.

4. GOAL for THIS workspace — what's driving research here? A project? Curiosity? Career growth? What would "success" look like in 3 months?

5. HYPOTHESIS / driving question — what is the spine of this workspace's research? Many users won't have one explicit yet — that's fine, mark it as "forming".

RULES:
- Ask ONE focused question at a time. Never multi-part.
- Follow up relentlessly — don't accept surface answers.
- For each area they mention, ask at least 2-3 calibration probes before moving on.
- Use THEIR language.
- Do NOT rush. A 12-15 turn conversation is expected.
- Track confidence per dimension. You need >90% on ALL.

WHEN YOU'RE DONE (turn 12+, all dimensions calibrated):
- First give a natural language summary of what you understood.
- Then output a JSON block in ```json fences:
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
          "too_basic": ["things that would be too elementary"]
        }
      ],
      "meta": {
        "paper_goal": "what they want from THIS workspace",
        "workspace_summary": "1-2 sentences describing this workspace's focus"
      },
      "hypothesis": {"statement": "their driving research question for this workspace, if any", "status": "forming|testing|refining"}
    }
  }

CRITICAL: Do NOT output JSON before turn 10 at minimum. If you find yourself ready at turn 6, you haven't probed deeply enough. Calibrate each area with specific technical questions.
"""

WORKSPACE_LEVEL_CONTINUE_PROMPT = """Continue the workspace-level onboarding interview. Ask ONE focused question at a time. You need per-area calibration (what they know, what's new, what's too basic). Don't rush — 12-15 turns is normal. Only output the profile_complete JSON when genuinely >90% confident on ALL dimensions."""


def handler(event: dict, context) -> dict:
    """Two-stage onboarding handler.

    GET  /onboarding         — returns status of both stages
    POST /onboarding         — send a message; the stage is auto-detected
                               (user-level if user META missing; else workspace-level)
                               or forced via body {"stage": "user"|"workspace"}.
    """
    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    method = event.get("httpMethod", "")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    if method == "GET":
        return _get_status(table, user_id, event)

    if method != "POST":
        return _response(405, {"error": "Method not allowed"})

    body = json.loads(event.get("body") or "{}")
    message = body.get("message", "").strip()

    # Decide which stage we're in
    requested_stage = (body.get("stage") or "").strip()
    user_meta_done = bool(db.get_user_meta(table, user_id))
    onboarding_marker = db.get_user_onboarding_status(table, user_id)
    user_onboarding_complete = bool(
        onboarding_marker and onboarding_marker.get("user_onboarding_complete")
    )

    if requested_stage == "user":
        stage = "user"
    elif requested_stage == "workspace":
        stage = "workspace"
    elif user_meta_done or user_onboarding_complete:
        stage = "workspace"
    else:
        stage = "user"

    if stage == "user":
        return _handle_user_stage(table, user_id, message)
    return _handle_workspace_stage(table, user_id, event, message)


def _get_status(table, user_id: str, event: dict) -> dict:
    """Return current onboarding status."""
    user_meta = db.get_user_meta(table, user_id)
    has_user_meta = bool(user_meta)
    onboarding_marker = db.get_user_onboarding_status(table, user_id)
    user_onboarding_complete = bool(
        onboarding_marker and onboarding_marker.get("user_onboarding_complete")
    )

    workspace_id = resolve_workspace_id(table, event, user_id)
    has_workspace_profile = False
    if workspace_id:
        ws_profile = db.get_full_profile(table, user_id, workspace_id)
        has_workspace_profile = bool(ws_profile.get("meta"))

    if has_user_meta and has_workspace_profile:
        next_stage = "complete"
    elif has_user_meta or user_onboarding_complete:
        next_stage = "workspace"
    else:
        next_stage = "user"

    return _response(200, {
        "has_user_meta": has_user_meta,
        "user_onboarding_complete": user_onboarding_complete or has_user_meta,
        "has_workspace_profile": has_workspace_profile,
        "workspace_id": workspace_id,
        "next_stage": next_stage,
        # Legacy compatibility for older clients:
        "has_profile": has_user_meta and has_workspace_profile,
    })


def _handle_user_stage(table, user_id: str, message: str) -> dict:
    """Conduct the user-level onboarding chat."""
    conv_id = "onboarding_user"
    # User-level onboarding lives outside any workspace — write directly to a
    # static partition.
    pk = f"USER#{user_id}#ONBOARDING_CONV"

    # Existing turns
    from boto3.dynamodb.conditions import Key
    turns_resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(pk) & Key("SK").begins_with("TURN#")
        ),
        ScanIndexForward=True,
    )
    turns = turns_resp.get("Items", [])

    # Hydration case: no new user message but turns already exist. Return the
    # last assistant response so the frontend can rehydrate the chat without
    # calling the LLM (which would fail — Bedrock rejects a history that
    # ends with an assistant message).
    if not message and turns:
        last_response = turns[-1].get("response", "")
        last_seq = turns[-1].get("seq", len(turns))
        user_meta_data = _extract_user_meta(last_response)
        if not user_meta_data:
            for turn in reversed(turns):
                user_meta_data = _extract_user_meta(turn.get("response", ""))
                if user_meta_data:
                    break
        result: dict = {
            "stage": "user",
            "response": last_response,
            "turn_seq": last_seq,
        }
        if user_meta_data:
            result["user_meta_complete"] = True
            result["summary"] = user_meta_data.get("summary", "")
            result["user_meta"] = user_meta_data.get("user_meta", {})
        return _response(200, result)

    llm_messages = []
    for turn in turns:
        if turn.get("request"):
            llm_messages.append({"role": "user", "content": turn["request"]})
        if turn.get("response"):
            llm_messages.append({"role": "assistant", "content": turn["response"]})

    if message:
        llm_messages.append({"role": "user", "content": message})

    system = USER_LEVEL_SYSTEM_PROMPT if not turns else USER_LEVEL_CONTINUE_PROMPT
    if not message and not turns:
        llm_messages.append({"role": "user", "content": "Hi, I just signed up."})

    response = call_llm_multi(
        system=system,
        messages=llm_messages,
        model_id="us.anthropic.claude-sonnet-4-6",
        max_tokens=8000,
        temperature=0.4,
    )
    if not response:
        return _response(500, {"error": "LLM call failed"})

    # Save turn
    seq = len(turns) + 1
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    user_msg = message or "Hi, I just signed up."
    table.put_item(Item={
        "PK": pk,
        "SK": f"TURN#{seq:05d}",
        "user_id": user_id,
        "seq": seq,
        "request": user_msg,
        "request_ts": ts,
        "response": response,
        "response_ts": ts,
    })

    user_meta_data = _extract_user_meta(response)
    if not user_meta_data:
        # Look back for a previous turn that already produced a complete block
        for turn in reversed(turns):
            user_meta_data = _extract_user_meta(turn.get("response", ""))
            if user_meta_data:
                break

    result: dict = {
        "stage": "user",
        "response": response,
        "turn_seq": seq,
    }
    if user_meta_data:
        result["user_meta_complete"] = True
        result["summary"] = user_meta_data.get("summary", "")
        result["user_meta"] = user_meta_data.get("user_meta", {})

    return _response(200, result)


def _handle_workspace_stage(table, user_id: str, event: dict, message: str) -> dict:
    """Conduct the workspace-level onboarding chat."""
    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    conv_id = "onboarding"
    conv = db.get_conversation_by_paper(table, user_id, workspace_id, conv_id)
    if conv is None:
        db.create_conversation(table, user_id, workspace_id, conv_id, "")

    turns = db.get_conversation_turns(table, user_id, workspace_id, conv_id)

    # Hydration case: no new user message but turns already exist. Return the
    # last assistant response so the frontend can rehydrate the chat without
    # calling the LLM (which would fail — Bedrock rejects a history that
    # ends with an assistant message).
    if not message and turns:
        last_response = turns[-1].get("response", "")
        last_seq = turns[-1].get("seq", len(turns))
        profile_data = _extract_profile(last_response)
        if not profile_data:
            for turn in reversed(turns):
                profile_data = _extract_profile(turn.get("response", ""))
                if profile_data:
                    break
        result: dict = {
            "stage": "workspace",
            "response": last_response,
            "turn_seq": last_seq,
            "workspace_id": workspace_id,
        }
        if profile_data:
            result["profile_complete"] = True
            result["profile_summary"] = profile_data.get("summary", "")
            result["profile"] = profile_data.get("profile", {})
        return _response(200, result)

    llm_messages = []
    for turn in turns:
        if turn.get("request"):
            llm_messages.append({"role": "user", "content": turn["request"]})
        if turn.get("response"):
            llm_messages.append({"role": "assistant", "content": turn["response"]})

    if message:
        llm_messages.append({"role": "user", "content": message})

    system = WORKSPACE_LEVEL_SYSTEM_PROMPT if not turns else WORKSPACE_LEVEL_CONTINUE_PROMPT
    if not message and not turns:
        # Inject the user-level meta as priming context
        user_meta = db.get_user_meta(table, user_id) or {}
        priming = ""
        if user_meta:
            priming = (
                f"(Context the user already gave us: background={user_meta.get('background','')}; "
                f"learning_style={user_meta.get('learning_style','')}; "
                f"math_comfort={user_meta.get('math_comfort','')}; "
                f"paper_preference={user_meta.get('paper_preference','')}.) "
            )
        llm_messages.append({"role": "user", "content": f"{priming}Let's set up this workspace."})

    response = call_llm_multi(
        system=system,
        messages=llm_messages,
        model_id="us.anthropic.claude-sonnet-4-6",
        max_tokens=24000,
        temperature=0.4,
    )
    if not response:
        return _response(500, {"error": "LLM call failed"})

    seq = len(turns) + 1
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    user_msg = message or "Let's set up this workspace."
    db.put_turn(table, user_id, workspace_id, conv_id, seq, user_msg, ts)
    db.update_turn_response(
        table, user_id, workspace_id, conv_id, seq, response, ts, [], 0, 0
    )
    db.update_conversation_last_active(table, user_id, workspace_id, conv_id)

    profile_data = _extract_profile(response)
    if not profile_data:
        for turn in reversed(turns):
            profile_data = _extract_profile(turn.get("response", ""))
            if profile_data:
                break

    result: dict = {
        "stage": "workspace",
        "response": response,
        "turn_seq": seq,
        "workspace_id": workspace_id,
    }
    if profile_data:
        result["profile_complete"] = True
        result["profile_summary"] = profile_data.get("summary", "")
        result["profile"] = profile_data.get("profile", {})

    return _response(200, result)


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------


def _extract_json_block(response: str) -> str | None:
    """Pull the first JSON block out of an LLM response."""
    fence_start = response.find("```json")
    if fence_start == -1:
        fence_start = response.find("```")
    json_str = None
    if fence_start != -1:
        try:
            content_start = response.index("\n", fence_start) + 1
            fence_end = response.find("```", content_start)
            if fence_end != -1:
                json_str = response[content_start:fence_end].strip()
        except ValueError:
            pass

    if not json_str:
        lines = response.split("\n")
        brace_start = None
        for i, line in enumerate(lines):
            if line.strip() == "{" or line.strip().startswith('{"'):
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

    return json_str


def _is_complete_flag(data: dict, flag: str) -> bool:
    """A completion is signalled either by type=="<flag>" or "<flag>": true.

    Models drift between {"type": "profile_complete", ...} and
    {"profile_complete": true, ...} — accept both.
    """
    if data.get("type") == flag:
        return True
    val = data.get(flag)
    return val is True or (isinstance(val, str) and val.lower() == "true")


def _unwrap_payload(data: dict, keys: tuple[str, ...]) -> dict:
    """If the meaningful fields are nested under a wrapper key, descend into it.

    Handles {"profile_complete": true, "user": {...}} and
    {"type": "profile_complete", "profile": {...}} uniformly.
    """
    for k in keys:
        inner = data.get(k)
        if isinstance(inner, dict) and inner:
            # Preserve a top-level summary if the wrapper doesn't carry one.
            if "summary" not in inner and "summary" in data:
                inner = {**inner, "summary": data["summary"]}
            return inner
    return data


def _extract_user_meta(response: str) -> dict | None:
    """Look for {type: 'user_meta_complete', user_meta: {...}}"""
    json_str = _extract_json_block(response)
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    explicit_type = data.get("type")
    if isinstance(explicit_type, str) and explicit_type and explicit_type != "user_meta_complete":
        return None

    is_complete = _is_complete_flag(data, "user_meta_complete")
    payload = _unwrap_payload(data, ("user_meta", "user"))

    if is_complete and data.get("user_meta"):
        return data
    # Fallback: any of the user-meta fields present (top-level or unwrapped)
    if is_complete or any(
        k in payload for k in ("background", "learning_style", "math_comfort", "paper_preference", "time_per_week")
    ):
        if not any(
            k in payload for k in ("background", "learning_style", "math_comfort", "paper_preference", "time_per_week")
        ):
            return None
        return {
            "type": "user_meta_complete",
            "summary": payload.get("summary", "") or data.get("summary", ""),
            "user_meta": {
                "background": payload.get("background", ""),
                "learning_style": payload.get("learning_style", {}),
                "math_comfort": payload.get("math_comfort", ""),
                "paper_preference": payload.get("paper_preference", ""),
                "time_per_week": payload.get("time_per_week", ""),
            },
        }
    return None


def _extract_profile(response: str) -> dict | None:
    """Look for the workspace-level profile JSON."""
    json_str = _extract_json_block(response)
    if not json_str:
        return None

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    if data.get("type") == "profile_complete" and data.get("profile"):
        return data

    # If the model explicitly typed this block as something other than a
    # profile completion, respect that and don't try to coerce it.
    explicit_type = data.get("type")
    if isinstance(explicit_type, str) and explicit_type and explicit_type != "profile_complete":
        return None

    is_complete = _is_complete_flag(data, "profile_complete")

    # Unwrap a nested payload if the profile fields live under a wrapper key
    # (profile / workspace / user / data). Models emit
    # {"profile_complete": true, "user": {...}} as often as the canonical shape.
    payload = _unwrap_payload(data, ("profile", "workspace", "user", "data"))

    profile_indicators = (
        "areas", "focus_areas", "research_areas", "level", "goal",
        "research_goals", "who", "what", "primary_focus", "role",
        "hypothesis", "domain",
    )
    if is_complete or any(k in payload for k in profile_indicators):
        # Require at least one substantive field so a bare flag with no content
        # doesn't produce an empty profile.
        if not any(k in payload for k in profile_indicators):
            return None
        return {
            "type": "profile_complete",
            "summary": payload.get("summary", "") or data.get("summary", ""),
            "profile": _normalize_profile(payload),
        }
    return None


def _normalize_profile(data: dict) -> dict:
    """Best-effort normalize a free-form profile JSON into the storage shape."""
    # Accept alternate keys the model sometimes uses for the areas list.
    areas_raw = data.get("areas")
    if not areas_raw:
        areas_raw = data.get("focus_areas") or data.get("research_areas") or []
    areas = []
    if isinstance(areas_raw, list):
        for item in areas_raw:
            if isinstance(item, dict):
                aid = item.get("id") or (item.get("label", "")[:30].lower().replace(" ", "-"))
                areas.append({
                    "id": aid,
                    "label": item.get("label", aid),
                    "role": item.get("role", "primary"),
                    "frontier": item.get("frontier", ""),
                    "current_level": item.get("current_level", "intermediate"),
                    "knows": item.get("knows", []),
                    "too_basic": item.get("too_basic", []),
                })
            else:
                slug = str(item).lower().replace(" ", "-")[:30]
                areas.append({"id": slug, "label": str(item), "role": "primary"})
    elif isinstance(areas_raw, dict):
        for role_key in ("primary", "core", "secondary", "adjacent"):
            for item in areas_raw.get(role_key, []) or []:
                if isinstance(item, dict):
                    aid = item.get("id") or (item.get("label", "")[:30].lower().replace(" ", "-"))
                    areas.append({
                        "id": aid,
                        "label": item.get("label", aid),
                        "role": "primary" if role_key in ("primary", "core") else "secondary",
                        "frontier": item.get("frontier", ""),
                        "current_level": item.get("current_level", "intermediate"),
                        "knows": item.get("knows", []),
                        "too_basic": item.get("too_basic", []),
                    })
                else:
                    slug = str(item).lower().replace(" ", "-")[:30]
                    areas.append({
                        "id": slug,
                        "label": str(item),
                        "role": "primary" if role_key in ("primary", "core") else "secondary",
                    })

    meta_raw = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    meta = {
        "paper_goal": meta_raw.get("paper_goal") or data.get("goal", "") or "",
        "workspace_summary": meta_raw.get("workspace_summary", ""),
    }

    hypothesis_raw = data.get("hypothesis", {})
    hypothesis = None
    if isinstance(hypothesis_raw, dict) and hypothesis_raw.get("statement"):
        hypothesis = {
            "statement": hypothesis_raw.get("statement", ""),
            "status": hypothesis_raw.get("status", "forming"),
        }
    elif isinstance(hypothesis_raw, str) and hypothesis_raw.strip():
        # Model sometimes emits the hypothesis as a bare string.
        hypothesis = {"statement": hypothesis_raw.strip(), "status": "forming"}

    return {"areas": areas, "meta": meta, "hypothesis": hypothesis}


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

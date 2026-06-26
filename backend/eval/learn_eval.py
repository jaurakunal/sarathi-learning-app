"""Eval harness for the Learn pipeline step.

Learn analyzes engagement events + conversations from a time window, then
emits a JSON profile-update payload (areas to strengthen, hypothesis evidence,
learning_style, reading_speed_wpm, summaries, changelog).

This is the fuzziest step to evaluate because the output is semantic prose +
loosely structured suggestions. Approach:

1. Build a synthetic but realistic input from the live user's data (engagement
   events + recent conversation turns) so the eval input is the same across
   models.
2. Run the candidate model — get candidate JSON output.
3. Run the baseline Sonnet model on the same input — get golden JSON output.
4. LLM-as-judge: score alignment between candidate and golden on three
   dimensions (areas, hypothesis_evidence, summaries) plus an overall verdict.

Single-input eval (vs digest's per-paper batch) — engagement+conversations
are bundled into one big input for the learn step.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from boto3.dynamodb.conditions import Key

from backend.eval import dataset as eval_dataset
from backend.eval.runner import PRICING_PER_1K, _approx_tokens
from backend.pipeline import learn as learn_module
from backend.shared import db
from backend.shared.llm import DEFAULT_MODEL_ID, call_llm, call_llm_with_usage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Build the eval input from dataset entries
# ---------------------------------------------------------------------------


def _aggregate_engagement_from_dataset(entries: list[dict]) -> dict:
    """Construct an engagement_stats dict like learn._aggregate_engagement
    would, but built from the dataset entries' engagement summaries (each entry
    has a `engagement` dict with read/dismissed/bookmarked/etc.).
    """
    stats: dict[str, Any] = {
        "total_events": 0,
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

    for entry in entries:
        paper_id = entry.get("paper_id", "")
        eng = entry.get("engagement") or {}
        # Each entry's engagement summary already counts each event once
        if eng.get("read"):
            stats["papers_read"].append(paper_id)
            stats["total_events"] += 1
        if eng.get("dismissed"):
            stats["papers_dismissed"].append(paper_id)
            stats["total_events"] += 1
        if eng.get("bookmarked"):
            stats["papers_bookmarked"].append(paper_id)
            stats["total_events"] += 1
        if eng.get("source_clicked"):
            stats["source_clicks"].append(paper_id)
            stats["total_events"] += 1
        if eng.get("viewed"):
            stats["views"] += 1
            stats["total_events"] += 1
        rated = eng.get("rated_value")
        if rated is not None:
            try:
                rv = int(rated)
                if rv >= 4:
                    stats["papers_rated_up"].append(paper_id)
                elif 0 < rv <= 2:
                    stats["papers_rated_down"].append(paper_id)
            except (TypeError, ValueError):
                pass
        if eng.get("time_on_page_ms"):
            try:
                stats["total_active_ms"] += int(eng["time_on_page_ms"])
            except (TypeError, ValueError):
                pass

    # Dedup
    for k in ("papers_read", "papers_dismissed", "papers_bookmarked",
              "papers_rated_up", "papers_rated_down", "source_clicks"):
        stats[k] = list(dict.fromkeys(stats[k]))
    return stats


def _conversations_from_dataset(entries: list[dict]) -> list[dict]:
    """Synthesize a `conversations` list from each entry's pinned_insights."""
    out = []
    for entry in entries:
        pinned = entry.get("pinned_insights") or []
        if not pinned:
            continue
        turns = [
            {"question": p.get("request", ""), "answer": p.get("response", "")}
            for p in pinned
            if p.get("request") or p.get("response")
        ]
        if not turns:
            continue
        out.append({
            "paper_id": entry.get("paper_id", ""),
            "turns": turns,
        })
    return out


def build_learn_input(table, user_id: str = eval_dataset.TEST_USER_ID) -> dict:
    """Materialize the (profile, engagement_stats, conversations) tuple.

    Reuses learn_module._aggregate_engagement when live engagement events are
    available; otherwise falls back to dataset-derived aggregation. This way
    the eval works whether or not engagement has been replayed onto the test
    user.
    """
    profile = db.get_full_profile(table, user_id)
    if not profile.get("meta"):
        raise RuntimeError(
            f"Test user {user_id} has no profile — run `eval_pipeline.py setup` first"
        )

    entries = eval_dataset.load_dataset(table)
    if not entries:
        raise RuntimeError(
            "No eval dataset found — run `eval_pipeline.py setup` first"
        )

    # Try real engagement first (last 30 days)
    end_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start_ts = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        events = db.list_engagement_events(table, user_id, start_ts, end_ts)
    except Exception:
        events = []

    if events:
        engagement_stats = learn_module._aggregate_engagement(events)
    else:
        engagement_stats = _aggregate_engagement_from_dataset(entries)

    conversations = _conversations_from_dataset(entries)

    return {
        "profile": profile,
        "engagement_stats": engagement_stats,
        "conversations": conversations,
    }


# ---------------------------------------------------------------------------
# Single-model run
# ---------------------------------------------------------------------------


def _parse_learn_json(text: Optional[str]) -> Optional[dict]:
    """Parse the Learn LLM JSON output, stripping markdown fences."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        return json.loads(s.strip())
    except json.JSONDecodeError:
        logger.warning("Learn returned invalid JSON: %s", s[:200])
        return None


def run_one_model(
    *,
    learn_input: dict,
    model: str,
) -> dict:
    """Execute the Learn LLM call with `model` on the prepared input."""
    profile = learn_input["profile"]
    engagement_stats = learn_input["engagement_stats"]
    conversations = learn_input["conversations"]

    user_message = learn_module._build_learn_prompt(
        profile, engagement_stats, conversations
    )
    system_prompt = learn_module.LEARN_SYSTEM_PROMPT

    start = time.time()
    raw_text, usage = call_llm_with_usage(
        system=system_prompt,
        user_message=user_message,
        model_id=model,
        max_tokens=8192,
        temperature=0.3,
    )
    elapsed = (time.time() - start) * 1000.0

    out: dict[str, Any] = {
        "model_used": model,
        "success": False,
        "latency_ms": int(elapsed),
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "raw_text": raw_text,
        "parsed": None,
        "error": None,
    }

    if raw_text is None:
        out["error"] = "llm_generation_failed"
        return out

    parsed = _parse_learn_json(raw_text)
    if not parsed:
        out["error"] = "learn_json_parse_failed"
        return out

    tokens_in = usage.get("tokens_in", 0) or (
        _approx_tokens(system_prompt) + _approx_tokens(user_message)
    )
    tokens_out = usage.get("tokens_out", 0) or _approx_tokens(raw_text)
    pricing = PRICING_PER_1K.get(model, {"in": 0.003, "out": 0.015})
    cost = (tokens_in / 1000.0) * pricing["in"] + (tokens_out / 1000.0) * pricing["out"]

    out.update({
        "success": True,
        "parsed": parsed,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
    })
    return out


# ---------------------------------------------------------------------------
# Alignment judge
# ---------------------------------------------------------------------------


_ALIGNMENT_JUDGE_SYSTEM = (
    "You are evaluating two profile-update suggestions for the same user "
    "engagement window. Judge whether the two updates suggest similar "
    "directional changes — not whether the wording matches.\n\n"
    "You MUST return ONLY a JSON object — no markdown, no commentary."
)


def _build_alignment_judge_prompt(*, candidate: dict, golden: dict) -> str:
    return (
        f"GOLDEN UPDATE (Sonnet baseline):\n"
        f"{json.dumps(golden, indent=2)[:6000]}\n\n"
        f"CANDIDATE UPDATE:\n"
        f"{json.dumps(candidate, indent=2)[:6000]}\n\n"
        "Rate alignment 1-5 on each dimension (5 = strongly aligned):\n"
        "- areas_alignment: do the two suggest similar area-status / frontier changes?\n"
        "- hypothesis_alignment: do they cite similar evidence (or both correctly say none)?\n"
        "- summaries_alignment: do the tiered summaries describe the same activity?\n"
        "- learning_style_alignment: do the learning_style + reading_speed updates agree?\n\n"
        "Return ONLY this JSON shape:\n"
        "{\n"
        '  "areas_alignment": <int 1-5>,\n'
        '  "hypothesis_alignment": <int 1-5>,\n'
        '  "summaries_alignment": <int 1-5>,\n'
        '  "learning_style_alignment": <int 1-5>,\n'
        '  "overall_alignment": <int 1-5>,\n'
        '  "rationale": "<one sentence>"\n'
        "}"
    )


def judge_alignment(
    *,
    candidate: dict,
    golden: dict,
    judge_model: str = DEFAULT_MODEL_ID,
) -> dict:
    """Score how aligned candidate updates are with golden updates."""
    raw = call_llm(
        system=_ALIGNMENT_JUDGE_SYSTEM,
        user_message=_build_alignment_judge_prompt(
            candidate=candidate, golden=golden
        ),
        model_id=judge_model,
        max_tokens=512,
        temperature=0.0,
    )
    out: dict[str, Any] = {
        "areas_alignment": None,
        "hypothesis_alignment": None,
        "summaries_alignment": None,
        "learning_style_alignment": None,
        "overall_alignment": None,
        "rationale": "",
        "raw_response": raw,
        "error": None,
    }
    if raw is None:
        out["error"] = "judge_call_failed"
        return out

    parsed = _parse_learn_json(raw)
    if not parsed:
        out["error"] = "judge_invalid_json"
        return out

    for k in ("areas_alignment", "hypothesis_alignment", "summaries_alignment",
              "learning_style_alignment", "overall_alignment"):
        v = parsed.get(k)
        if isinstance(v, (int, float)):
            out[k] = int(v)
    out["rationale"] = str(parsed.get("rationale", ""))
    return out


# ---------------------------------------------------------------------------
# Run-level orchestration
# ---------------------------------------------------------------------------


def run_eval(
    table,
    *,
    model: str = DEFAULT_MODEL_ID,
    judge_model: str = DEFAULT_MODEL_ID,
    baseline_model: str = DEFAULT_MODEL_ID,
    user_id: str = eval_dataset.TEST_USER_ID,
) -> dict:
    """Run learn eval: generate candidate output + golden Sonnet output + judge.

    Stores results under EVAL#LEARN#<run_id>. Returns the run summary.

    NOTE: If model == baseline_model, we run the LLM only once (it's the
    same call) and the alignment judge will compare identical outputs.
    """
    learn_input = build_learn_input(table, user_id=user_id)

    run_id = f"{db._now_iso()}_{uuid.uuid4().hex[:8]}"
    started = time.time()

    logger.info(
        "Learn eval run %s: model=%s baseline=%s judge=%s",
        run_id, model, baseline_model, judge_model,
    )

    # Candidate run
    cand = run_one_model(learn_input=learn_input, model=model)

    # Golden run (Sonnet baseline). Skip if same model.
    if model == baseline_model:
        gold = dict(cand)
    else:
        gold = run_one_model(learn_input=learn_input, model=baseline_model)

    alignment: Optional[dict] = None
    if cand.get("success") and gold.get("success"):
        alignment = judge_alignment(
            candidate=cand["parsed"],
            golden=gold["parsed"],
            judge_model=judge_model,
        )
    else:
        alignment = {"error": "candidate_or_golden_failed"}

    pk = f"EVAL#LEARN#{run_id}"

    # Persist a single per-paper-style record (only one input here).
    detail_item = {
        "PK": pk,
        "SK": "DETAIL#main",
        "candidate_model": cand.get("model_used"),
        "candidate_success": cand.get("success"),
        "candidate_parsed": cand.get("parsed"),
        "candidate_error": cand.get("error"),
        "golden_model": gold.get("model_used"),
        "golden_success": gold.get("success"),
        "golden_parsed": gold.get("parsed"),
        "golden_error": gold.get("error"),
        "alignment": alignment,
    }
    table.put_item(Item=db._sanitize_item(detail_item))

    total_cost = float(cand.get("cost_usd", 0.0)) + (
        float(gold.get("cost_usd", 0.0)) if model != baseline_model else 0.0
    )
    total_in = int(cand.get("tokens_in", 0)) + (
        int(gold.get("tokens_in", 0)) if model != baseline_model else 0
    )
    total_out = int(cand.get("tokens_out", 0)) + (
        int(gold.get("tokens_out", 0)) if model != baseline_model else 0
    )

    summary = {
        "PK": pk,
        "SK": "META",
        "step": "learn",
        "run_id": run_id,
        "model": model,
        "baseline_model": baseline_model,
        "judge_model": judge_model,
        "started_at": db._now_iso(),
        "candidate_success": cand.get("success", False),
        "golden_success": gold.get("success", False),
        "candidate_latency_ms": cand.get("latency_ms", 0),
        "golden_latency_ms": gold.get("latency_ms", 0) if model != baseline_model else 0,
        "tokens_in_total": total_in,
        "tokens_out_total": total_out,
        "total_cost_usd": round(total_cost, 6),
        "elapsed_seconds": round(time.time() - started, 2),
        "areas_alignment": (alignment or {}).get("areas_alignment"),
        "hypothesis_alignment": (alignment or {}).get("hypothesis_alignment"),
        "summaries_alignment": (alignment or {}).get("summaries_alignment"),
        "learning_style_alignment": (alignment or {}).get("learning_style_alignment"),
        "overall_alignment": (alignment or {}).get("overall_alignment"),
        "alignment_error": (alignment or {}).get("error"),
    }
    table.put_item(Item=db._sanitize_item(summary))

    logger.info(
        "Learn eval %s done: overall_alignment=%s $%.4f",
        run_id, summary["overall_alignment"], total_cost,
    )
    return {k: v for k, v in summary.items() if k not in ("PK", "SK")}


def list_runs(table) -> list[dict]:
    from boto3.dynamodb.conditions import Attr
    resp = table.scan(
        FilterExpression=(
            Attr("PK").begins_with("EVAL#LEARN#") & Attr("SK").eq("META")
        )
    )
    items = list(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = table.scan(
            FilterExpression=(
                Attr("PK").begins_with("EVAL#LEARN#") & Attr("SK").eq("META")
            ),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    items.sort(key=lambda i: i.get("started_at", ""))
    return items


def load_run_detail(table, run_id: str) -> Optional[dict]:
    resp = table.get_item(Key={"PK": f"EVAL#LEARN#{run_id}", "SK": "DETAIL#main"})
    return resp.get("Item")

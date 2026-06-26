"""Eval harness for the Triage pipeline step.

Triage scores each paper with `worth_my_hours` (bool) and `triage_score` (0-1
float) plus a level + hypothesis_relevant. The Sonnet baseline outputs are
already stored on each paper record in the live user's data — we capture
them in the eval dataset (alongside golden cards) and compare candidate
model outputs against them.

Metrics:
- triage_score MAE + Pearson correlation (continuous)
- worth_my_hours classification accuracy (boolean)
- level classification accuracy (3-class)

This is pure-code comparison — no LLM-as-judge — because the output is a
small structured numeric/classification result.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import math
import time
import uuid
from typing import Any, Optional

from boto3.dynamodb.conditions import Key

from backend.eval import dataset as eval_dataset
from backend.eval.runner import PRICING_PER_1K, _approx_tokens
from backend.pipeline import triage as triage_module
from backend.shared import db
from backend.shared.llm import DEFAULT_MODEL_ID, call_llm_with_usage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-paper run
# ---------------------------------------------------------------------------


def _parse_triage_json(text: str) -> Optional[dict]:
    """Parse the triage JSON response, stripping code fences if present."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        logger.warning("Triage returned invalid JSON: %s", text[:200])
        return None


def run_one_paper(
    *,
    entry: dict,
    profile: dict,
    model: str,
) -> dict:
    """Run triage with `model` on a single dataset entry.

    Returns dict with paper_id, success, candidate {worth_my_hours, triage_score,
    level, hypothesis_relevant, reasoning}, golden {same fields},
    cost/latency/tokens.
    """
    paper_id = entry.get("paper_id", "")
    paper = entry.get("paper") or {}

    # Golden values — Sonnet's output stored on the paper record
    golden = {
        "worth_my_hours": paper.get("worth_my_hours"),
        "triage_score": paper.get("triage_score"),
        "level": paper.get("triage_level"),
        "hypothesis_relevant": paper.get("hypothesis_relevant"),
        "reasoning": paper.get("triage_reasoning"),
    }

    result: dict[str, Any] = {
        "paper_id": paper_id,
        "success": False,
        "model_used": model,
        "latency_ms": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "candidate": None,
        "golden": golden,
        "error": None,
    }

    if golden["worth_my_hours"] is None and golden["triage_score"] is None:
        result["error"] = "missing_golden_triage"
        return result

    # Reuse production prompt builders
    system_prompt = triage_module._build_system_prompt()
    user_message = triage_module._build_user_message(paper, profile)

    start = time.time()
    raw_text, usage = call_llm_with_usage(
        system=system_prompt,
        user_message=user_message,
        model_id=model,
        max_tokens=500,
    )
    elapsed = (time.time() - start) * 1000.0

    if raw_text is None:
        result["error"] = "llm_generation_failed"
        result["latency_ms"] = int(elapsed)
        return result

    parsed = _parse_triage_json(raw_text)
    if not parsed:
        result["error"] = "triage_json_parse_failed"
        result["latency_ms"] = int(elapsed)
        return result

    # Coerce + clamp to match production behavior
    try:
        triage_score = float(parsed.get("triage_score", 0))
    except (TypeError, ValueError):
        triage_score = 0.0
    triage_score = max(0.0, min(1.0, triage_score))

    level = parsed.get("level", "just_right")
    if level not in ("too_basic", "just_right", "over_head"):
        level = "just_right"

    candidate = {
        "worth_my_hours": bool(parsed.get("worth_my_hours", False)),
        "triage_score": triage_score,
        "level": level,
        "hypothesis_relevant": bool(parsed.get("hypothesis_relevant", False)),
        "reasoning": str(parsed.get("reasoning", "")),
    }

    tokens_in = usage.get("tokens_in", 0) or (
        _approx_tokens(system_prompt) + _approx_tokens(user_message)
    )
    tokens_out = usage.get("tokens_out", 0) or _approx_tokens(raw_text)
    pricing = PRICING_PER_1K.get(model, {"in": 0.003, "out": 0.015})
    cost = (tokens_in / 1000.0) * pricing["in"] + (tokens_out / 1000.0) * pricing["out"]

    result.update({
        "success": True,
        "candidate": candidate,
        "latency_ms": int(elapsed),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
    })
    return result


# ---------------------------------------------------------------------------
# Metric calculators
# ---------------------------------------------------------------------------


def _coerce_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_mae(pairs: list[tuple[float, float]]) -> float:
    """Mean absolute error between candidate and golden values."""
    if not pairs:
        return 0.0
    total = sum(abs(c - g) for c, g in pairs)
    return round(total / len(pairs), 4)


def compute_pearson(pairs: list[tuple[float, float]]) -> float:
    """Pearson correlation between candidate and golden values.

    Returns 0.0 if fewer than 2 points or if either series has zero variance.
    """
    if len(pairs) < 2:
        return 0.0
    n = len(pairs)
    sum_c = sum(c for c, _ in pairs)
    sum_g = sum(g for _, g in pairs)
    mean_c = sum_c / n
    mean_g = sum_g / n
    num = sum((c - mean_c) * (g - mean_g) for c, g in pairs)
    denom_c = math.sqrt(sum((c - mean_c) ** 2 for c, _ in pairs))
    denom_g = math.sqrt(sum((g - mean_g) ** 2 for _, g in pairs))
    if denom_c == 0 or denom_g == 0:
        return 0.0
    return round(num / (denom_c * denom_g), 4)


def compute_classification_accuracy(pairs: list[tuple[Any, Any]]) -> float:
    """Fraction where candidate == golden."""
    if not pairs:
        return 0.0
    matches = sum(1 for c, g in pairs if c == g)
    return round(matches / len(pairs), 4)


def aggregate_triage_results(per_paper: list[dict]) -> dict:
    """Compute MAE + correlation + classification accuracy across results."""
    score_pairs: list[tuple[float, float]] = []
    worth_pairs: list[tuple[bool, bool]] = []
    level_pairs: list[tuple[str, str]] = []
    hyp_pairs: list[tuple[bool, bool]] = []

    for r in per_paper:
        if not r.get("success"):
            continue
        cand = r.get("candidate") or {}
        gold = r.get("golden") or {}

        c_score = _coerce_float(cand.get("triage_score"))
        g_score = _coerce_float(gold.get("triage_score"))
        if c_score is not None and g_score is not None:
            score_pairs.append((c_score, g_score))

        c_worth = cand.get("worth_my_hours")
        g_worth = gold.get("worth_my_hours")
        if c_worth is not None and g_worth is not None:
            worth_pairs.append((bool(c_worth), bool(g_worth)))

        c_level = cand.get("level")
        g_level = gold.get("level")
        if c_level and g_level:
            level_pairs.append((c_level, g_level))

        c_hyp = cand.get("hypothesis_relevant")
        g_hyp = gold.get("hypothesis_relevant")
        if c_hyp is not None and g_hyp is not None:
            hyp_pairs.append((bool(c_hyp), bool(g_hyp)))

    return {
        "papers_evaluated": sum(1 for r in per_paper if r.get("success")),
        "triage_score_mae": compute_mae(score_pairs),
        "triage_score_pearson": compute_pearson(score_pairs),
        "worth_my_hours_accuracy": compute_classification_accuracy(worth_pairs),
        "level_accuracy": compute_classification_accuracy(level_pairs),
        "hypothesis_relevant_accuracy": compute_classification_accuracy(hyp_pairs),
    }


# ---------------------------------------------------------------------------
# Whole-run orchestration
# ---------------------------------------------------------------------------


def run_eval(
    table,
    *,
    model: str = DEFAULT_MODEL_ID,
    user_id: str = eval_dataset.TEST_USER_ID,
    max_workers: int = 5,
) -> dict:
    """Run triage with `model` over the persisted eval dataset.

    Stores results under EVAL#TRIAGE#<run_id>. Returns the run summary.
    """
    profile = db.get_full_profile(table, user_id)
    if not profile.get("meta"):
        raise RuntimeError(
            f"Test user {user_id} has no profile — run `eval_pipeline.py setup` first"
        )

    entries = eval_dataset.load_dataset(table)
    if not entries:
        raise RuntimeError("No eval dataset found — run `eval_pipeline.py setup` first")

    run_id = f"{db._now_iso()}_{uuid.uuid4().hex[:8]}"
    started = time.time()

    logger.info(
        "Triage eval run %s: model=%s papers=%d workers=%d",
        run_id, model, len(entries), max_workers,
    )

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(run_one_paper, entry=entry, profile=profile, model=model)
            for entry in entries
        ]
        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                logger.exception("Triage worker raised: %s", e)
                results.append({
                    "paper_id": "",
                    "success": False,
                    "model_used": model,
                    "error": f"worker_exception: {e}",
                })

    aggregate = aggregate_triage_results(results)
    successes = aggregate["papers_evaluated"]
    total_cost = sum(r.get("cost_usd", 0.0) for r in results)
    total_in = sum(r.get("tokens_in", 0) for r in results)
    total_out = sum(r.get("tokens_out", 0) for r in results)
    total_latency = sum(r.get("latency_ms", 0) for r in results)

    pk = f"EVAL#TRIAGE#{run_id}"
    for r in results:
        if not r.get("paper_id"):
            continue
        item = {"PK": pk, "SK": f"PAPER#{r['paper_id']}", **r}
        table.put_item(Item=db._sanitize_item(item))

    summary = {
        "PK": pk,
        "SK": "META",
        "step": "triage",
        "run_id": run_id,
        "model": model,
        "started_at": db._now_iso(),
        "papers_total": len(entries),
        "papers_succeeded": successes,
        "papers_failed": len(entries) - successes,
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_per_paper_usd": round(total_cost / max(successes, 1), 6),
        "tokens_in_total": total_in,
        "tokens_out_total": total_out,
        "avg_latency_ms": int(total_latency / max(successes, 1)),
        "elapsed_seconds": round(time.time() - started, 2),
        **aggregate,
    }
    table.put_item(Item=db._sanitize_item(summary))

    logger.info(
        "Triage eval %s done: %d/%d ok, MAE=%.3f corr=%.3f worth_acc=%.3f $%.4f",
        run_id, successes, len(entries),
        aggregate["triage_score_mae"], aggregate["triage_score_pearson"],
        aggregate["worth_my_hours_accuracy"], total_cost,
    )
    return {k: v for k, v in summary.items() if k not in ("PK", "SK")}


def list_runs(table) -> list[dict]:
    """Return all triage eval META records."""
    from boto3.dynamodb.conditions import Attr
    resp = table.scan(
        FilterExpression=(
            Attr("PK").begins_with("EVAL#TRIAGE#") & Attr("SK").eq("META")
        )
    )
    items = list(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = table.scan(
            FilterExpression=(
                Attr("PK").begins_with("EVAL#TRIAGE#") & Attr("SK").eq("META")
            ),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    items.sort(key=lambda i: i.get("started_at", ""))
    return items


def load_run_papers(table, run_id: str) -> list[dict]:
    """Return all per-paper triage eval results for a given run."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"EVAL#TRIAGE#{run_id}") & Key("SK").begins_with("PAPER#")
        ),
    )
    return resp.get("Items", [])

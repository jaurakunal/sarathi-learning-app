"""Eval harness for the Lens pipeline step.

Lens annotates each feed card with a free-text `hypothesis_relevance` field
(supports / refutes / refines / irrelevant + 1-2 sentences of reasoning).

We compare:
1. The verdict (supports/refutes/refines/irrelevant) extracted from candidate
   text vs the same verdict extracted from the golden Sonnet output. This is
   pure code (keyword classification).
2. Reasoning coherence — one cheap LLM-as-judge call per paper that returns
   "yes/no" on whether the reasoning logically connects the paper to the
   hypothesis.

Combined metric: lens_alignment = pct of papers where verdicts match AND
reasoning is judged coherent.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import time
import uuid
from typing import Any, Optional

from boto3.dynamodb.conditions import Key

from backend.eval import dataset as eval_dataset
from backend.eval.runner import PRICING_PER_1K, _approx_tokens
from backend.pipeline import lens as lens_module
from backend.shared import db
from backend.shared.llm import DEFAULT_MODEL_ID, call_llm, call_llm_with_usage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Verdict extraction
# ---------------------------------------------------------------------------


# Verdicts in priority order — first match wins so "supports and refines" → supports
_VERDICT_PATTERNS = (
    ("supports", re.compile(r"\bsupport(?:s|ed|ing)?\b", re.IGNORECASE)),
    ("refutes", re.compile(r"\brefut(?:es?|ed|ing)?\b|\bcontradict", re.IGNORECASE)),
    ("refines", re.compile(r"\brefine(?:s|d|ment)?\b|\bnuance|\bqualif", re.IGNORECASE)),
    ("irrelevant", re.compile(r"\birrelevant\b|\bdoes not relate\b|\bno connection\b|\bunrelated\b", re.IGNORECASE)),
)


def extract_verdict(text: Optional[str]) -> str:
    """Reduce a free-text hypothesis_relevance annotation to one of:
    supports / refutes / refines / irrelevant / unknown.
    """
    if not text:
        return "unknown"
    s = text.strip()
    for label, pat in _VERDICT_PATTERNS:
        if pat.search(s):
            return label
    return "unknown"


# ---------------------------------------------------------------------------
# Reasoning judge (cheap LLM call)
# ---------------------------------------------------------------------------


_REASONING_JUDGE_SYSTEM = (
    "You are a strict reasoning evaluator. Given a hypothesis, a paper "
    "summary, and a one-sentence assessment of whether the paper supports, "
    "refutes, or refines the hypothesis, decide whether the assessment's "
    "REASONING is coherent and well-grounded. Coherent = the assessment "
    "actually references something from the paper that connects to the "
    "hypothesis. Incoherent = generic, contradictory, or hallucinated. "
    "Reply with ONLY \"yes\" or \"no\"."
)


def _build_reasoning_judge_prompt(
    *, hypothesis: str, paper: dict, candidate_text: str
) -> str:
    title = paper.get("title", "")
    abstract = (paper.get("abstract") or "")[:1200]
    return (
        f"HYPOTHESIS:\n{hypothesis}\n\n"
        f"PAPER:\nTitle: {title}\nAbstract: {abstract}\n\n"
        f"CANDIDATE ASSESSMENT:\n{candidate_text}\n\n"
        f"Is the candidate's reasoning coherent? Reply ONLY \"yes\" or \"no\"."
    )


def judge_reasoning_coherent(
    *,
    hypothesis: str,
    paper: dict,
    candidate_text: str,
    judge_model: str = DEFAULT_MODEL_ID,
) -> Optional[bool]:
    """Returns True if judge says yes, False if no, None on failure."""
    if not candidate_text:
        return False
    raw = call_llm(
        system=_REASONING_JUDGE_SYSTEM,
        user_message=_build_reasoning_judge_prompt(
            hypothesis=hypothesis, paper=paper, candidate_text=candidate_text,
        ),
        model_id=judge_model,
        max_tokens=8,
        temperature=0.0,
    )
    if raw is None:
        return None
    s = raw.strip().lower()
    if s.startswith("yes"):
        return True
    if s.startswith("no"):
        return False
    # Tolerate a leading quote / punctuation
    s = re.sub(r"^[\"'`*\s]+", "", s)
    if s.startswith("yes"):
        return True
    if s.startswith("no"):
        return False
    return None


# ---------------------------------------------------------------------------
# Single-paper run
# ---------------------------------------------------------------------------


def run_one_paper(
    *,
    entry: dict,
    hypothesis_statement: str,
    model: str,
    judge_model: str = DEFAULT_MODEL_ID,
    skip_reasoning_judge: bool = False,
) -> dict:
    """Run lens against the golden card for `entry`, judge the result."""
    paper_id = entry.get("paper_id", "")
    paper = entry.get("paper") or {}
    golden_card = entry.get("golden_card") or {}

    # Golden value: the lens annotation already on the golden card
    golden_text = golden_card.get("hypothesis_relevance") or ""
    golden_verdict = extract_verdict(golden_text)

    result: dict[str, Any] = {
        "paper_id": paper_id,
        "success": False,
        "model_used": model,
        "judge_model": judge_model,
        "latency_ms": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "candidate_text": None,
        "candidate_verdict": None,
        "golden_text": golden_text,
        "golden_verdict": golden_verdict,
        "verdict_match": None,
        "reasoning_coherent": None,
        "error": None,
    }

    if not golden_card:
        result["error"] = "missing_golden_card"
        return result

    system_prompt = lens_module.SYSTEM_PROMPT
    user_message = lens_module._build_user_message(hypothesis_statement, golden_card)

    start = time.time()
    raw_text, usage = call_llm_with_usage(
        system=system_prompt,
        user_message=user_message,
        model_id=model,
        max_tokens=300,
    )
    elapsed = (time.time() - start) * 1000.0

    if raw_text is None:
        result["error"] = "llm_generation_failed"
        result["latency_ms"] = int(elapsed)
        return result

    candidate_text = raw_text.strip()
    candidate_verdict = extract_verdict(candidate_text)
    verdict_match = (candidate_verdict == golden_verdict and candidate_verdict != "unknown")

    reasoning_coherent: Optional[bool] = None
    if not skip_reasoning_judge:
        reasoning_coherent = judge_reasoning_coherent(
            hypothesis=hypothesis_statement,
            paper=paper,
            candidate_text=candidate_text,
            judge_model=judge_model,
        )

    tokens_in = usage.get("tokens_in", 0) or (
        _approx_tokens(system_prompt) + _approx_tokens(user_message)
    )
    tokens_out = usage.get("tokens_out", 0) or _approx_tokens(candidate_text)
    pricing = PRICING_PER_1K.get(model, {"in": 0.003, "out": 0.015})
    cost = (tokens_in / 1000.0) * pricing["in"] + (tokens_out / 1000.0) * pricing["out"]

    result.update({
        "success": True,
        "candidate_text": candidate_text,
        "candidate_verdict": candidate_verdict,
        "verdict_match": verdict_match,
        "reasoning_coherent": reasoning_coherent,
        "latency_ms": int(elapsed),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
    })
    return result


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_lens_results(per_paper: list[dict]) -> dict:
    """Compute verdict accuracy + reasoning coherence + combined alignment."""
    n = sum(1 for r in per_paper if r.get("success"))
    matches = sum(1 for r in per_paper if r.get("success") and r.get("verdict_match"))
    coherent = sum(
        1 for r in per_paper if r.get("success") and r.get("reasoning_coherent") is True
    )
    aligned = sum(
        1 for r in per_paper
        if r.get("success") and r.get("verdict_match")
        and r.get("reasoning_coherent") is True
    )

    # Per-class verdict distribution (candidate)
    cand_distribution: dict[str, int] = {}
    for r in per_paper:
        if not r.get("success"):
            continue
        v = r.get("candidate_verdict") or "unknown"
        cand_distribution[v] = cand_distribution.get(v, 0) + 1

    return {
        "papers_evaluated": n,
        "verdict_match_pct": round(100.0 * matches / max(n, 1), 1),
        "reasoning_coherent_pct": round(100.0 * coherent / max(n, 1), 1),
        "lens_alignment_pct": round(100.0 * aligned / max(n, 1), 1),
        "candidate_verdict_distribution": cand_distribution,
    }


# ---------------------------------------------------------------------------
# Whole-run orchestration
# ---------------------------------------------------------------------------


def run_eval(
    table,
    *,
    model: str = DEFAULT_MODEL_ID,
    judge_model: str = DEFAULT_MODEL_ID,
    user_id: str = eval_dataset.TEST_USER_ID,
    max_workers: int = 5,
    skip_reasoning_judge: bool = False,
) -> dict:
    """Run lens with `model` over the eval dataset, judge each result."""
    profile = db.get_full_profile(table, user_id)
    if not profile.get("meta"):
        raise RuntimeError(
            f"Test user {user_id} has no profile — run `eval_pipeline.py setup` first"
        )

    hypothesis_item = profile.get("hypothesis") or {}
    hypothesis_statement = hypothesis_item.get("statement", "")
    if not hypothesis_statement:
        raise RuntimeError("No hypothesis on test profile — cannot run lens eval")

    entries = eval_dataset.load_dataset(table)
    if not entries:
        raise RuntimeError("No eval dataset found — run `eval_pipeline.py setup` first")

    run_id = f"{db._now_iso()}_{uuid.uuid4().hex[:8]}"
    started = time.time()

    logger.info(
        "Lens eval run %s: model=%s judge=%s papers=%d workers=%d",
        run_id, model, judge_model, len(entries), max_workers,
    )

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                run_one_paper,
                entry=entry,
                hypothesis_statement=hypothesis_statement,
                model=model,
                judge_model=judge_model,
                skip_reasoning_judge=skip_reasoning_judge,
            )
            for entry in entries
        ]
        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                logger.exception("Lens worker raised: %s", e)
                results.append({
                    "paper_id": "",
                    "success": False,
                    "model_used": model,
                    "error": f"worker_exception: {e}",
                })

    aggregate = aggregate_lens_results(results)
    successes = aggregate["papers_evaluated"]
    total_cost = sum(r.get("cost_usd", 0.0) for r in results)
    total_in = sum(r.get("tokens_in", 0) for r in results)
    total_out = sum(r.get("tokens_out", 0) for r in results)
    total_latency = sum(r.get("latency_ms", 0) for r in results)

    pk = f"EVAL#LENS#{run_id}"
    for r in results:
        if not r.get("paper_id"):
            continue
        item = {"PK": pk, "SK": f"PAPER#{r['paper_id']}", **r}
        # Trim long fields
        for key in ("candidate_text", "golden_text"):
            if isinstance(item.get(key), str):
                item[key] = item[key][:4000]
        table.put_item(Item=db._sanitize_item(item))

    summary = {
        "PK": pk,
        "SK": "META",
        "step": "lens",
        "run_id": run_id,
        "model": model,
        "judge_model": judge_model,
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
        "Lens eval %s done: %d/%d ok, verdict_match=%.1f%% coherent=%.1f%% align=%.1f%% $%.4f",
        run_id, successes, len(entries),
        aggregate["verdict_match_pct"],
        aggregate["reasoning_coherent_pct"],
        aggregate["lens_alignment_pct"],
        total_cost,
    )
    return {k: v for k, v in summary.items() if k not in ("PK", "SK")}


def list_runs(table) -> list[dict]:
    from boto3.dynamodb.conditions import Attr
    resp = table.scan(
        FilterExpression=(
            Attr("PK").begins_with("EVAL#LENS#") & Attr("SK").eq("META")
        )
    )
    items = list(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = table.scan(
            FilterExpression=(
                Attr("PK").begins_with("EVAL#LENS#") & Attr("SK").eq("META")
            ),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    items.sort(key=lambda i: i.get("started_at", ""))
    return items


def load_run_papers(table, run_id: str) -> list[dict]:
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"EVAL#LENS#{run_id}") & Key("SK").begins_with("PAPER#")
        ),
    )
    return resp.get("Items", [])

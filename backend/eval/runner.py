"""Run digest generation against the eval dataset with a candidate model.

This deliberately reuses the digest step's prompt-building helpers
(_build_profile_context, _build_system_prompt, _build_user_prompt,
_generate_card) so the eval is a faithful comparison of the actual prompt
the model would see in production.

Full text is read from the golden card's S3 key — we never re-fetch from
the source. That keeps the eval deterministic and avoids upstream rate limits.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
import uuid
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key

from backend.eval import dataset as eval_dataset
from backend.pipeline import digest as digest_module
from backend.shared import db
from backend.shared.llm import DEFAULT_MODEL_ID

logger = logging.getLogger(__name__)


# Approximate Bedrock pricing per 1K tokens for cost reporting
# (rough estimates — kept in code so /report has something to print).
PRICING_PER_1K = {
    "us.anthropic.claude-sonnet-4-6":      {"in": 0.003, "out": 0.015},
    "us.anthropic.claude-opus-4-7":        {"in": 0.015, "out": 0.075},
    "us.anthropic.claude-haiku-4-5":       {"in": 0.001, "out": 0.005},
    "us.anthropic.claude-3-5-sonnet-v2":   {"in": 0.003, "out": 0.015},
    "us.anthropic.claude-3-5-haiku":       {"in": 0.0008, "out": 0.004},
}


def _approx_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) when Bedrock doesn't return usage."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Reset: wipe paper data on the test user (keep profile + conversations)
# ---------------------------------------------------------------------------


def reset_test_user(table, user_id: str = eval_dataset.TEST_USER_ID) -> int:
    """Delete: paper records, feed cards, library entries, engagement events.
    Keep: profile (META + AREAs + HYPOTHESIS), conversations, push subs.

    Returns the number of items deleted.
    """
    deleted = 0

    # 1. Feed cards (single-PK)
    pk_feed = f"USER#{user_id}#FEED"
    resp = table.query(KeyConditionExpression=Key("PK").eq(pk_feed))
    items = resp.get("Items", [])
    if items:
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        deleted += len(items)

    # 2. Engagement events
    pk_eng = f"USER#{user_id}#ENGAGEMENT"
    resp = table.query(KeyConditionExpression=Key("PK").eq(pk_eng))
    items = resp.get("Items", [])
    if items:
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        deleted += len(items)

    # 3. Per-paper records (PK pattern: USER#<u>#PAPER#<id>) — must scan
    from boto3.dynamodb.conditions import Attr
    paper_prefix = f"USER#{user_id}#PAPER#"
    library_prefix = f"USER#{user_id}#LIBRARY#"

    response = table.scan(
        FilterExpression=(
            Attr("PK").begins_with(paper_prefix) | Attr("PK").begins_with(library_prefix)
        )
    )
    targets = list(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.scan(
            FilterExpression=(
                Attr("PK").begins_with(paper_prefix) | Attr("PK").begins_with(library_prefix)
            ),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        targets.extend(response.get("Items", []))

    if targets:
        with table.batch_writer() as batch:
            for item in targets:
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        deleted += len(targets)

    logger.info("Reset test user %s: deleted %d items", user_id, deleted)
    return deleted


# ---------------------------------------------------------------------------
# Single-paper run: build prompts and call LLM with model X
# ---------------------------------------------------------------------------


def _read_full_text(s3_client, s3_bucket: str, s3_key: str) -> Optional[str]:
    """Read full text from S3. Returns None on failure."""
    try:
        resp = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        return resp["Body"].read().decode("utf-8", errors="replace")
    except Exception:
        logger.exception("Could not read full_text from s3://%s/%s", s3_bucket, s3_key)
        return None


def run_one_paper(
    *,
    entry: dict,
    profile: dict,
    model: str,
    s3_client: Any,
    s3_bucket: str,
) -> dict:
    """Generate a candidate card for a single dataset entry.

    Returns a result dict with keys: paper_id, success, model_used, latency_ms,
    tokens_in, tokens_out, cost_usd, candidate_card, error (optional).
    """
    paper_id = entry.get("paper_id", "")
    paper = entry.get("paper") or {}
    golden = entry.get("golden_card") or {}
    # Try golden card first, then derive from convention (live user's S3 path)
    s3_key = golden.get("full_text_s3_key", "")
    if not s3_key and paper_id:
        s3_key = f"users/{eval_dataset.LIVE_USER_ID}/papers/{paper_id}/full_text.txt"

    result = {
        "paper_id": paper_id,
        "success": False,
        "model_used": model,
        "latency_ms": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "candidate_card": None,
        "error": None,
    }

    if not s3_key:
        result["error"] = "missing_full_text_s3_key"
        return result

    full_text = _read_full_text(s3_client, s3_bucket, s3_key)
    if not full_text:
        result["error"] = "full_text_not_readable"
        return result

    profile_context = digest_module._build_profile_context(profile)
    system_prompt = digest_module._build_system_prompt(profile_context)
    user_prompt = digest_module._build_user_prompt(paper, full_text)

    start = time.time()
    card = digest_module._generate_card(model, system_prompt, user_prompt)
    elapsed = (time.time() - start) * 1000.0

    if card is None:
        result["error"] = "llm_generation_failed"
        result["latency_ms"] = int(elapsed)
        return result

    tokens_in = _approx_tokens(system_prompt) + _approx_tokens(user_prompt)
    # Roughly approximate output tokens from the JSON serialization
    import json as _json
    tokens_out = _approx_tokens(_json.dumps(card))

    pricing = PRICING_PER_1K.get(model, {"in": 0.003, "out": 0.015})
    cost = (tokens_in / 1000.0) * pricing["in"] + (tokens_out / 1000.0) * pricing["out"]

    result.update({
        "success": True,
        "candidate_card": card,
        "latency_ms": int(elapsed),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
    })
    return result


# ---------------------------------------------------------------------------
# Whole-run orchestration
# ---------------------------------------------------------------------------


def run_eval(
    table,
    *,
    model: str = DEFAULT_MODEL_ID,
    s3_bucket: str,
    user_id: str = eval_dataset.TEST_USER_ID,
    max_workers: int = 5,
    s3_client: Optional[Any] = None,
) -> dict:
    """Run the digest task with `model` over the persisted eval dataset.

    Stores results under EVAL#RUN#<run_id>. Returns the run summary.
    """
    if s3_client is None:
        s3_client = boto3.client("s3")

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
        "Eval run %s: model=%s papers=%d workers=%d",
        run_id, model, len(entries), max_workers,
    )

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                run_one_paper,
                entry=entry,
                profile=profile,
                model=model,
                s3_client=s3_client,
                s3_bucket=s3_bucket,
            )
            for entry in entries
        ]
        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                logger.exception("Worker raised: %s", e)
                results.append({
                    "paper_id": "",
                    "success": False,
                    "model_used": model,
                    "error": f"worker_exception: {e}",
                })

    successes = sum(1 for r in results if r.get("success"))
    total_cost = sum(r.get("cost_usd", 0.0) for r in results)
    total_in = sum(r.get("tokens_in", 0) for r in results)
    total_out = sum(r.get("tokens_out", 0) for r in results)
    total_latency = sum(r.get("latency_ms", 0) for r in results)

    # Persist per-paper results
    for r in results:
        if not r.get("paper_id"):
            continue
        item = {
            "PK": f"EVAL#RUN#{run_id}",
            "SK": f"PAPER#{r['paper_id']}",
            **r,
        }
        table.put_item(Item=db._sanitize_item(item))

    summary = {
        "PK": f"EVAL#RUN#{run_id}",
        "SK": "META",
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
    }
    table.put_item(Item=db._sanitize_item(summary))

    logger.info(
        "Eval run %s complete: %d/%d ok, $%.4f total",
        run_id, successes, len(entries), total_cost,
    )
    # Strip DDB internals before returning
    return {k: v for k, v in summary.items() if k not in ("PK", "SK")}


def list_runs(table) -> list[dict]:
    """Return all eval run META records (for /report)."""
    # Scan EVAL#RUN#* — these run IDs aren't enumerable via a single query.
    from boto3.dynamodb.conditions import Attr
    resp = table.scan(
        FilterExpression=(
            Attr("PK").begins_with("EVAL#RUN#") & Attr("SK").eq("META")
        )
    )
    items = list(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = table.scan(
            FilterExpression=(
                Attr("PK").begins_with("EVAL#RUN#") & Attr("SK").eq("META")
            ),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    items.sort(key=lambda i: i.get("started_at", ""))
    return items


def load_run_papers(table, run_id: str) -> list[dict]:
    """Return all per-paper results for a given run (for /judge)."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"EVAL#RUN#{run_id}") & Key("SK").begins_with("PAPER#")
        ),
    )
    return resp.get("Items", [])

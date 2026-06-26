"""Eval harness for the Relevance Filter (pre-triage discover step).

The relevance filter is a coarse "is this paper in the user's ballpark?" check
that runs in batches. Production code returns the FILTERED subset of papers;
for eval we want per-paper labels (kept vs rejected) so we can compute
classification metrics.

Approach:
- Positive class: the 18 papers in EVAL#DATASET (they all passed the filter
  in production, since they made it all the way to digested status).
- Negative class: REAL near-miss papers from EVAL#DATASET_NEG — papers that
  Sonnet rejected at triage with off-topic / not-relevant reasoning. These
  are harder than synthetic negatives because they're in adjacent CS
  subfields rather than blatantly different domains. Falls back to the
  synthetic `SYNTHETIC_OFFTOPIC_PAPERS` list when the negative dataset
  hasn't been populated.

The eval reuses the production prompt construction (SYSTEM_PROMPT + the
indexed-paper-list user message) but invokes `call_llm_with_usage` instead of
`call_llm` so we can attribute token costs.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Optional

from boto3.dynamodb.conditions import Key

from backend.eval import dataset as eval_dataset
from backend.eval.runner import PRICING_PER_1K, _approx_tokens
from backend.shared import db, relevance_filter as rf_module
from backend.shared.llm import DEFAULT_MODEL_ID, call_llm_with_usage
from backend.shared.models import Area

logger = logging.getLogger(__name__)


# Synthetic off-topic papers used as the "rejected" negative class.
# Each paper has the canonical fields the filter expects (title, abstract).
# These are intentionally far from AI/ML/agent topics — pure biology, civil
# engineering, food science — so a competent filter MUST reject them all.
SYNTHETIC_OFFTOPIC_PAPERS: list[dict] = [
    {
        "id": "synth-offtopic-001",
        "title": "Migration Patterns of Atlantic Bluefin Tuna in the Mediterranean",
        "abstract": (
            "We tagged 240 Atlantic bluefin tuna with satellite trackers across "
            "three breeding seasons. Results show consistent winter migration to "
            "the Strait of Gibraltar with summer feeding in the Tyrrhenian Sea."
        ),
    },
    {
        "id": "synth-offtopic-002",
        "title": "Concrete Compressive Strength Under Sub-Zero Curing Conditions",
        "abstract": (
            "Construction in cold climates requires curing additives. We tested "
            "calcium nitrate accelerators in concrete mixes cured at -10°C and "
            "report 28-day compressive strength gains of up to 38% vs control."
        ),
    },
    {
        "id": "synth-offtopic-003",
        "title": "Sourdough Starter Microbial Communities Across Hydration Levels",
        "abstract": (
            "We sequenced 16S rRNA from 84 sourdough starters at hydrations "
            "ranging 60-110%. Lactobacillus plantarum dominated drier starters "
            "while wetter starters favored Saccharomyces cerevisiae."
        ),
    },
    {
        "id": "synth-offtopic-004",
        "title": "Geomagnetic Field Reversal Patterns in the Cretaceous-Paleogene",
        "abstract": (
            "Paleomagnetic samples from 28 sites across North America were "
            "analyzed for polarity reversals across the K-Pg boundary. We "
            "identify three brief reversal events not captured in prior records."
        ),
    },
    {
        "id": "synth-offtopic-005",
        "title": "Phenology of Alpine Wildflowers Under Late Snowmelt",
        "abstract": (
            "Late snowmelt years produced a 14-day delay in peak bloom for "
            "Anemone occidentalis. We document a corresponding mismatch with "
            "bumblebee emergence dates across five subalpine meadows."
        ),
    },
    {
        "id": "synth-offtopic-006",
        "title": "Roman Concrete Self-Healing via Volcanic Ash Inclusions",
        "abstract": (
            "We characterized inclusions in 2nd-century Roman maritime concrete. "
            "Hot-mixing with volcanic ash creates calcium-aluminum-silicate-"
            "hydrate phases that reseal microcracks in seawater."
        ),
    },
    {
        "id": "synth-offtopic-007",
        "title": "Cold Brew Coffee Extraction Kinetics at Low Temperature",
        "abstract": (
            "We measured extraction yield, total dissolved solids, and pH in "
            "cold-brew coffee at 4°C, 12°C, and 22°C across grind sizes. Cold "
            "extraction reduced acid yield by 67% while preserving caffeine."
        ),
    },
    {
        "id": "synth-offtopic-008",
        "title": "Honeybee Forager Recruitment via Vibration Signals",
        "abstract": (
            "Apis mellifera workers produce vibration signals on the comb to "
            "modulate recruit foraging. We video-tracked 12 colonies and report "
            "a 2.3x increase in forager departure rate following pulses."
        ),
    },
    {
        "id": "synth-offtopic-009",
        "title": "Sediment Transport in Braided Rivers under Glacial Retreat",
        "abstract": (
            "We tracked bedload sediment in three Alaskan braided rivers over "
            "five summers. Deglaciation increased peak summer transport rates "
            "by an order of magnitude relative to pre-1990 measurements."
        ),
    },
    {
        "id": "synth-offtopic-010",
        "title": "Pollen Tube Growth Dynamics in Arabidopsis Thaliana",
        "abstract": (
            "Confocal imaging of GFP-labeled pollen tubes reveals oscillatory "
            "calcium gradients at the tip during navigation toward the ovule. "
            "We characterize three new mutant lines with disrupted gradients."
        ),
    },
    {
        "id": "synth-offtopic-011",
        "title": "Stellar Population Synthesis in Dwarf Spheroidal Galaxies",
        "abstract": (
            "Resolved photometry of six Milky Way satellite galaxies reveals "
            "extended star formation histories with a metal-poor old population "
            "and a younger intermediate-age burst around 6 Gyr ago."
        ),
    },
    {
        "id": "synth-offtopic-012",
        "title": "Wear Resistance of Boron-Carbide-Coated Cutting Tools",
        "abstract": (
            "We deposited B4C coatings via PVD onto WC-Co cutting tools and "
            "evaluated tool life on 4140 steel. Coated tools showed 3.1x life "
            "extension at standard cutting speeds and feeds."
        ),
    },
]


# ---------------------------------------------------------------------------
# Areas extraction (production filter expects backend.shared.models.Area objects)
# ---------------------------------------------------------------------------


def _profile_to_areas(profile: dict) -> list[Area]:
    """Build a list of `Area` dataclasses from a stored profile dict."""
    out: list[Area] = []
    for raw in profile.get("areas") or []:
        area_id = raw.get("id") or raw.get("area_id") or ""
        if not area_id:
            continue
        try:
            out.append(Area(
                id=area_id,
                user_id=raw.get("user_id", ""),
                label=raw.get("label", area_id),
                status=raw.get("status", "active"),
                role=raw.get("role", "secondary"),
                links=list(raw.get("links") or []),
                frontier=raw.get("frontier", "") or "",
                too_basic=list(raw.get("too_basic") or []),
                just_right=list(raw.get("just_right") or []),
            ))
        except Exception:
            logger.exception("Could not coerce area %s into Area model", area_id)
    return out


# ---------------------------------------------------------------------------
# Single batch call (with token usage)
# ---------------------------------------------------------------------------


def _build_relevance_user_message(papers: list[dict], areas: list[Area]) -> str:
    """Reuses the production prompt format from relevance_filter.batch_relevance_filter."""
    areas_desc = "\n".join(
        f"- {a.label}: {', '.join(a.just_right[:3])}" for a in areas
    )
    paper_list = "\n".join(
        f"[{i}] {p.get('title', 'Untitled')}\n    {p.get('abstract', '')[:200]}"
        for i, p in enumerate(papers)
    )
    return (
        f"Research areas:\n{areas_desc}\n\n"
        f"Papers to evaluate ({len(papers)} total):\n{paper_list}\n\n"
        f"Return a JSON array of indices (0-based) for papers relevant to ANY of the research areas above. "
        f"Be inclusive — only exclude clearly irrelevant papers."
    )


def _parse_indices(text: str, n_papers: int) -> Optional[list[int]]:
    """Extract integer indices from the LLM response."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        # strip ```json or ``` ... ```
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [i for i in parsed if isinstance(i, int) and 0 <= i < n_papers]


def run_one_batch(
    *,
    papers: list[dict],
    areas: list[Area],
    model: str,
) -> dict:
    """Run the relevance filter on one batch and return per-paper kept flags."""
    user_message = _build_relevance_user_message(papers, areas)

    start = time.time()
    raw_text, usage = call_llm_with_usage(
        system=rf_module.SYSTEM_PROMPT,
        user_message=user_message,
        model_id=model,
        max_tokens=1000,
    )
    elapsed = (time.time() - start) * 1000.0

    out: dict[str, Any] = {
        "success": False,
        "model_used": model,
        "latency_ms": int(elapsed),
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "kept_indices": [],
        "error": None,
    }

    if raw_text is None:
        out["error"] = "llm_generation_failed"
        return out

    indices = _parse_indices(raw_text, len(papers))
    if indices is None:
        out["error"] = "indices_parse_failed"
        return out

    tokens_in = usage.get("tokens_in", 0) or (
        _approx_tokens(rf_module.SYSTEM_PROMPT) + _approx_tokens(user_message)
    )
    tokens_out = usage.get("tokens_out", 0) or _approx_tokens(raw_text)
    pricing = PRICING_PER_1K.get(model, {"in": 0.003, "out": 0.015})
    cost = (tokens_in / 1000.0) * pricing["in"] + (tokens_out / 1000.0) * pricing["out"]

    out.update({
        "success": True,
        "kept_indices": sorted(set(indices)),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
    })
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_classification_metrics(
    *, kept: list[bool], golden: list[bool]
) -> dict:
    """Compute accuracy / precision / recall / F1 against golden labels.

    `golden=True` = paper SHOULD be kept (positive class).
    """
    if not kept or not golden or len(kept) != len(golden):
        return {
            "accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0,
            "tp": 0, "fp": 0, "tn": 0, "fn": 0,
        }
    tp = fp = tn = fn = 0
    for k, g in zip(kept, golden):
        if g and k:
            tp += 1
        elif g and not k:
            fn += 1
        elif (not g) and k:
            fp += 1
        else:
            tn += 1
    n = len(kept)
    accuracy = (tp + tn) / max(n, 1)
    precision = tp / max(tp + fp, 1) if (tp + fp) > 0 else 0.0
    recall = tp / max(tp + fn, 1) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0 else 0.0
    )
    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


# ---------------------------------------------------------------------------
# Whole-run orchestration
# ---------------------------------------------------------------------------


_OFFTOPIC_KEYWORDS = (
    "off-topic", "off topic", "not relevant", "not related",
    "outside the user's areas", "outside scope", "unrelated",
    "different domain", "irrelevant", "not in scope",
)


def _is_near_miss_negative(paper: dict) -> bool:
    """Heuristic: a candidate paper is a "near-miss" relevance negative if its
    Sonnet triage reasoning indicates the paper was rejected for being
    off-topic / outside the user's areas (rather than e.g. too-basic).

    We also accept any paper whose hypothesis_relevant=False AND
    triage_score is low (< 0.4), which catches papers Sonnet decisively
    deemed off-area without explicit keyword matches.
    """
    reasoning = (paper.get("triage_reasoning") or "").lower()
    if any(k in reasoning for k in _OFFTOPIC_KEYWORDS):
        return True
    try:
        score = float(paper.get("triage_score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    if (
        paper.get("hypothesis_relevant") is False
        and score < 0.4
    ):
        return True
    return False


def _select_real_negatives(table, target: int = 25) -> list[dict]:
    """Pull real near-miss negative papers from EVAL#DATASET_NEG.

    Returns up to `target` papers that look like off-topic rejects. Returns
    an empty list if the negative dataset isn't populated yet (caller falls
    back to synthetic).
    """
    neg_entries = eval_dataset.load_negative_dataset(table)
    candidates: list[dict] = []
    fallback: list[dict] = []
    for e in neg_entries:
        paper = e.get("paper") or {}
        if not paper.get("title"):
            continue
        if _is_near_miss_negative(paper):
            candidates.append(paper)
        else:
            fallback.append(paper)

    # Stable order so re-running doesn't churn the eval set
    candidates.sort(key=lambda p: p.get("id", ""))
    fallback.sort(key=lambda p: p.get("id", ""))
    out = candidates[:target]
    if len(out) < target:
        # Backfill with whatever rejected papers we have so the negative
        # class isn't tiny — anything Sonnet rejected is still a useful
        # negative signal.
        out.extend(fallback[: target - len(out)])
    return out


def _build_eval_paper_set(table, prefer_real_negatives: bool = True) -> list[dict]:
    """Construct the eval paper set.

    Positives = papers in EVAL#DATASET. Negatives = real near-miss papers
    from EVAL#DATASET_NEG when available, else the synthetic off-topic
    papers.

    Each paper dict gains a `_golden_keep` bool that the filter does NOT
    see.
    """
    entries = eval_dataset.load_dataset(table)
    positives = []
    for e in entries:
        p = e.get("paper") or {}
        if p.get("title"):
            positives.append({**p, "_golden_keep": True})

    real_neg_papers: list[dict] = []
    if prefer_real_negatives:
        real_neg_papers = _select_real_negatives(table, target=25)

    if real_neg_papers:
        negatives = [{**p, "_golden_keep": False} for p in real_neg_papers]
    else:
        negatives = [{**p, "_golden_keep": False} for p in SYNTHETIC_OFFTOPIC_PAPERS]

    return positives + negatives


def run_eval(
    table,
    *,
    model: str = DEFAULT_MODEL_ID,
    user_id: str = eval_dataset.TEST_USER_ID,
    batch_size: int = 25,
    prefer_real_negatives: bool = True,
) -> dict:
    """Run relevance filter eval. Stores results under EVAL#RELEVANCE#<run_id>."""
    profile = db.get_full_profile(table, user_id)
    if not profile.get("meta"):
        raise RuntimeError(
            f"Test user {user_id} has no profile — run `eval_pipeline.py setup` first"
        )

    areas = _profile_to_areas(profile)
    if not areas:
        raise RuntimeError("Test profile has no areas — cannot run relevance eval")

    all_papers = _build_eval_paper_set(
        table, prefer_real_negatives=prefer_real_negatives,
    )
    # Track whether negatives are real near-misses or synthetic fallback
    real_neg_count = 0
    if prefer_real_negatives:
        real_neg_count = len(_select_real_negatives(table, target=25))
    negatives_source = "real" if real_neg_count > 0 else "synthetic"
    n_positives = sum(1 for p in all_papers if p["_golden_keep"])
    if n_positives == 0:
        raise RuntimeError(
            "No eval dataset positives found — run `eval_pipeline.py setup` first"
        )

    run_id = f"{db._now_iso()}_{uuid.uuid4().hex[:8]}"
    started = time.time()

    logger.info(
        "Relevance eval run %s: model=%s positives=%d negatives=%d batch=%d",
        run_id, model,
        sum(1 for p in all_papers if p["_golden_keep"]),
        sum(1 for p in all_papers if not p["_golden_keep"]),
        batch_size,
    )

    # Run in batches to stay within the production filter's context budget.
    per_paper_results: list[dict] = []
    total_cost = 0.0
    total_in = 0
    total_out = 0
    total_latency_ms = 0
    n_batches = 0

    for offset in range(0, len(all_papers), batch_size):
        batch = all_papers[offset:offset + batch_size]
        # Pass only the public paper fields to the filter — strip _golden_keep
        public_batch = [{k: v for k, v in p.items() if not k.startswith("_")} for p in batch]
        out = run_one_batch(papers=public_batch, areas=areas, model=model)
        n_batches += 1

        if not out["success"]:
            for p in batch:
                per_paper_results.append({
                    "paper_id": p.get("id", ""),
                    "title": p.get("title", ""),
                    "golden_keep": p["_golden_keep"],
                    "candidate_keep": None,
                    "match": None,
                    "error": out.get("error"),
                })
            continue

        kept_set = set(out["kept_indices"])
        for i, p in enumerate(batch):
            kept = i in kept_set
            per_paper_results.append({
                "paper_id": p.get("id", ""),
                "title": p.get("title", ""),
                "golden_keep": p["_golden_keep"],
                "candidate_keep": kept,
                "match": kept == p["_golden_keep"],
                "error": None,
            })

        total_cost += out["cost_usd"]
        total_in += out["tokens_in"]
        total_out += out["tokens_out"]
        total_latency_ms += out["latency_ms"]

    successful_calls = [r for r in per_paper_results if r["candidate_keep"] is not None]
    kept_labels = [bool(r["candidate_keep"]) for r in successful_calls]
    golden_labels = [bool(r["golden_keep"]) for r in successful_calls]
    metrics = compute_classification_metrics(kept=kept_labels, golden=golden_labels)

    pk = f"EVAL#RELEVANCE#{run_id}"
    for r in per_paper_results:
        if not r["paper_id"]:
            continue
        item = {"PK": pk, "SK": f"PAPER#{r['paper_id']}", **r}
        table.put_item(Item=db._sanitize_item(item))

    summary = {
        "PK": pk,
        "SK": "META",
        "step": "relevance",
        "run_id": run_id,
        "model": model,
        "started_at": db._now_iso(),
        "papers_total": len(all_papers),
        "positives_total": sum(1 for p in all_papers if p["_golden_keep"]),
        "negatives_total": sum(1 for p in all_papers if not p["_golden_keep"]),
        "negatives_source": negatives_source,
        "papers_evaluated": len(successful_calls),
        "n_batches": n_batches,
        "batch_size": batch_size,
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_per_paper_usd": round(total_cost / max(len(successful_calls), 1), 6),
        "tokens_in_total": total_in,
        "tokens_out_total": total_out,
        "avg_latency_ms": int(total_latency_ms / max(n_batches, 1)),
        "elapsed_seconds": round(time.time() - started, 2),
        **metrics,
    }
    table.put_item(Item=db._sanitize_item(summary))

    logger.info(
        "Relevance eval %s: acc=%.3f prec=%.3f rec=%.3f f1=%.3f $%.4f",
        run_id, metrics["accuracy"], metrics["precision"],
        metrics["recall"], metrics["f1"], total_cost,
    )
    return {k: v for k, v in summary.items() if k not in ("PK", "SK")}


def list_runs(table) -> list[dict]:
    from boto3.dynamodb.conditions import Attr
    resp = table.scan(
        FilterExpression=(
            Attr("PK").begins_with("EVAL#RELEVANCE#") & Attr("SK").eq("META")
        )
    )
    items = list(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = table.scan(
            FilterExpression=(
                Attr("PK").begins_with("EVAL#RELEVANCE#") & Attr("SK").eq("META")
            ),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    items.sort(key=lambda i: i.get("started_at", ""))
    return items


def load_run_papers(table, run_id: str) -> list[dict]:
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"EVAL#RELEVANCE#{run_id}") & Key("SK").begins_with("PAPER#")
        ),
    )
    return resp.get("Items", [])

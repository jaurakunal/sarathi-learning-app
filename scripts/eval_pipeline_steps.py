"""LLM evaluation harness for the four non-digest pipeline steps.

Companion to `eval_pipeline.py` which evaluates the digest step. This script
covers triage, lens, relevance filter, and learn — each of which has
structured (numeric / classification) outputs rather than free-form cards,
so the evaluator is pure-code comparison + (for lens / learn) a brief
LLM-as-judge call rather than the full digest judge.

Usage:
    AWS_PROFILE=poc python scripts/eval_pipeline_steps.py triage --model zai.glm-5
    AWS_PROFILE=poc python scripts/eval_pipeline_steps.py lens --model moonshotai.kimi-k2.5
    AWS_PROFILE=poc python scripts/eval_pipeline_steps.py relevance --model moonshotai.kimi-k2.5
    AWS_PROFILE=poc python scripts/eval_pipeline_steps.py learn --model moonshotai.kimi-k2.5
    AWS_PROFILE=poc python scripts/eval_pipeline_steps.py all --models moonshotai.kimi-k2.5,zai.glm-5
    AWS_PROFILE=poc python scripts/eval_pipeline_steps.py report
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `backend` importable when this script is invoked directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from backend.eval import dataset as eval_dataset
from backend.eval import learn_eval, lens_eval, relevance_eval, triage_eval
from backend.shared.llm import DEFAULT_MODEL_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eval_pipeline_steps")


TABLE_NAME_DEFAULT = os.environ.get("SARATHI_TABLE", "sarathi")
REGION_DEFAULT = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_table(table_name: str, region: str):
    session = boto3.Session(region_name=region)
    return session.resource("dynamodb").Table(table_name)


def _jsonable(obj):
    """Convert Decimals (from DDB) so json.dumps doesn't choke."""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# Single-step subcommands
# ---------------------------------------------------------------------------


def cmd_triage(args) -> int:
    table = _get_table(args.table, args.region)
    summary = triage_eval.run_eval(
        table, model=args.model, max_workers=args.workers,
        user_id=eval_dataset.TEST_USER_ID,
    )
    logger.info("Triage eval summary: %s", json.dumps(_jsonable(summary), indent=2))
    return 0 if summary.get("papers_succeeded", 0) > 0 else 1


def cmd_lens(args) -> int:
    table = _get_table(args.table, args.region)
    summary = lens_eval.run_eval(
        table, model=args.model, judge_model=args.judge_model,
        max_workers=args.workers, skip_reasoning_judge=args.skip_judge,
        user_id=eval_dataset.TEST_USER_ID,
    )
    logger.info("Lens eval summary: %s", json.dumps(_jsonable(summary), indent=2))
    return 0 if summary.get("papers_succeeded", 0) > 0 else 1


def cmd_relevance(args) -> int:
    table = _get_table(args.table, args.region)
    summary = relevance_eval.run_eval(
        table, model=args.model, batch_size=args.batch_size,
        user_id=eval_dataset.TEST_USER_ID,
    )
    logger.info("Relevance eval summary: %s", json.dumps(_jsonable(summary), indent=2))
    return 0 if summary.get("papers_evaluated", 0) > 0 else 1


def cmd_learn(args) -> int:
    table = _get_table(args.table, args.region)
    summary = learn_eval.run_eval(
        table, model=args.model,
        baseline_model=args.baseline_model,
        judge_model=args.judge_model,
        user_id=eval_dataset.TEST_USER_ID,
    )
    logger.info("Learn eval summary: %s", json.dumps(_jsonable(summary), indent=2))
    return 0 if summary.get("candidate_success") else 1


# ---------------------------------------------------------------------------
# Multi-model orchestration
# ---------------------------------------------------------------------------


def cmd_all(args) -> int:
    """Run all 4 step evals for each candidate model."""
    table = _get_table(args.table, args.region)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        logger.error("No models supplied")
        return 1

    overall_ok = True
    for model in models:
        logger.info("=" * 60)
        logger.info("Running ALL step evals for model: %s", model)
        logger.info("=" * 60)
        for step_name, fn in [
            ("triage", lambda: triage_eval.run_eval(
                table, model=model, max_workers=args.workers,
                user_id=eval_dataset.TEST_USER_ID,
            )),
            ("lens", lambda: lens_eval.run_eval(
                table, model=model, judge_model=args.judge_model,
                max_workers=args.workers, skip_reasoning_judge=args.skip_judge,
                user_id=eval_dataset.TEST_USER_ID,
            )),
            ("relevance", lambda: relevance_eval.run_eval(
                table, model=model, batch_size=args.batch_size,
                user_id=eval_dataset.TEST_USER_ID,
            )),
            ("learn", lambda: learn_eval.run_eval(
                table, model=model, baseline_model=args.baseline_model,
                judge_model=args.judge_model, user_id=eval_dataset.TEST_USER_ID,
            )),
        ]:
            try:
                summary = fn()
                logger.info("[%s/%s] OK: %s", model, step_name, _short_summary(step_name, summary))
            except Exception as e:
                logger.exception("[%s/%s] FAILED: %s", model, step_name, e)
                overall_ok = False

    return 0 if overall_ok else 1


def _short_summary(step: str, summary: dict) -> str:
    """One-line summary per step."""
    s = _jsonable(summary)
    if step == "triage":
        return (
            f"papers={s.get('papers_succeeded')}/{s.get('papers_total')} "
            f"score_mae={s.get('triage_score_mae')} "
            f"corr={s.get('triage_score_pearson')} "
            f"worth_acc={s.get('worth_my_hours_accuracy')} "
            f"$={s.get('total_cost_usd')}"
        )
    if step == "lens":
        return (
            f"papers={s.get('papers_succeeded')}/{s.get('papers_total')} "
            f"verdict_match={s.get('verdict_match_pct')}% "
            f"coherent={s.get('reasoning_coherent_pct')}% "
            f"align={s.get('lens_alignment_pct')}% "
            f"$={s.get('total_cost_usd')}"
        )
    if step == "relevance":
        return (
            f"acc={s.get('accuracy')} prec={s.get('precision')} "
            f"rec={s.get('recall')} f1={s.get('f1')} $={s.get('total_cost_usd')}"
        )
    if step == "learn":
        return (
            f"overall_align={s.get('overall_alignment')} "
            f"areas={s.get('areas_alignment')} "
            f"summaries={s.get('summaries_alignment')} "
            f"$={s.get('total_cost_usd')}"
        )
    return json.dumps(s)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def cmd_report(args) -> int:
    """Consolidate all eval results into a markdown report."""
    table = _get_table(args.table, args.region)

    triage_runs = [_jsonable(r) for r in triage_eval.list_runs(table)]
    lens_runs = [_jsonable(r) for r in lens_eval.list_runs(table)]
    relevance_runs = [_jsonable(r) for r in relevance_eval.list_runs(table)]
    learn_runs = [_jsonable(r) for r in learn_eval.list_runs(table)]

    md = render_markdown(
        triage_runs=triage_runs,
        lens_runs=lens_runs,
        relevance_runs=relevance_runs,
        learn_runs=learn_runs,
    )

    if args.output:
        out_path = Path(args.output)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = Path(f"sarathi_eval_pipeline_steps_{ts}.md")
    out_path.write_text(md)
    print(md)
    print(f"\nReport written to: {out_path}")
    return 0


def render_markdown(
    *,
    triage_runs: list[dict],
    lens_runs: list[dict],
    relevance_runs: list[dict],
    learn_runs: list[dict],
) -> str:
    """Render a consolidated markdown report across all 4 steps."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        "# Sarathi Pipeline Steps Evaluation",
        "",
        f"_Generated: {ts}_",
        "",
        f"_Baseline model: `{DEFAULT_MODEL_ID}`_",
        "",
    ]

    # ---------- Triage ----------
    lines.extend([
        "## Triage",
        "",
        "Per-paper score (worth_my_hours bool + triage_score 0-1) compared to "
        "the live user's stored Sonnet outputs. MAE = mean absolute error on "
        "triage_score; Corr = Pearson correlation; Worth Acc = boolean accuracy.",
        "",
        "| Model | Papers | Score MAE | Score Corr | Worth Acc | Level Acc | $/paper | Latency (ms) |",
        "|---|---|---|---|---|---|---|---|",
    ])
    if triage_runs:
        for r in triage_runs:
            lines.append(
                f"| `{r.get('model','?')}` | {r.get('papers_succeeded',0)}/{r.get('papers_total',0)} | "
                f"{_fmt_num(r.get('triage_score_mae'))} | {_fmt_num(r.get('triage_score_pearson'))} | "
                f"{_fmt_num(r.get('worth_my_hours_accuracy'))} | {_fmt_num(r.get('level_accuracy'))} | "
                f"${_fmt_num(r.get('avg_cost_per_paper_usd'), 4)} | {r.get('avg_latency_ms', 0)} |"
            )
        best = _best_triage(triage_runs)
        if best:
            lines.extend([
                "",
                f"**Recommendation:** `{best['model']}` — best balance of accuracy "
                f"(worth_acc={_fmt_num(best.get('worth_my_hours_accuracy'))}, "
                f"score_mae={_fmt_num(best.get('triage_score_mae'))}) and cost "
                f"(${_fmt_num(best.get('avg_cost_per_paper_usd'), 4)}/paper).",
            ])
    else:
        lines.append("| _no runs_ | | | | | | | |")
    lines.append("")

    # ---------- Lens ----------
    lines.extend([
        "## Lens",
        "",
        "Hypothesis-relevance annotation. Verdict match = fraction where the "
        "candidate reaches the same supports/refutes/refines verdict as Sonnet. "
        "Coherent = LLM-as-judge says reasoning is well-grounded. Lens align = "
        "both verdict matches AND reasoning coherent.",
        "",
        "| Model | Papers | Verdict Match % | Coherent % | Lens Align % | $/paper | Latency (ms) |",
        "|---|---|---|---|---|---|---|",
    ])
    if lens_runs:
        for r in lens_runs:
            lines.append(
                f"| `{r.get('model','?')}` | {r.get('papers_succeeded',0)}/{r.get('papers_total',0)} | "
                f"{_fmt_num(r.get('verdict_match_pct'), 1)} | "
                f"{_fmt_num(r.get('reasoning_coherent_pct'), 1)} | "
                f"{_fmt_num(r.get('lens_alignment_pct'), 1)} | "
                f"${_fmt_num(r.get('avg_cost_per_paper_usd'), 4)} | "
                f"{r.get('avg_latency_ms', 0)} |"
            )
        best = _best_lens(lens_runs)
        if best:
            lines.extend([
                "",
                f"**Recommendation:** `{best['model']}` — top lens_alignment "
                f"({_fmt_num(best.get('lens_alignment_pct'), 1)}%) at "
                f"${_fmt_num(best.get('avg_cost_per_paper_usd'), 4)}/paper.",
            ])
    else:
        lines.append("| _no runs_ | | | | | | |")
    lines.append("")

    # ---------- Relevance ----------
    lines.extend([
        "## Relevance Filter",
        "",
        "Coarse pre-triage filter. Positives = the 18 dataset papers (which "
        "passed in production). Negatives = synthetic off-topic papers shipped "
        "with the eval. Precision = of papers kept, fraction that should be "
        "kept; Recall = of papers that should be kept, fraction actually kept.",
        "",
        "| Model | Papers | Accuracy | Precision | Recall | F1 | $/paper | Avg Latency (ms) |",
        "|---|---|---|---|---|---|---|---|",
    ])
    if relevance_runs:
        for r in relevance_runs:
            lines.append(
                f"| `{r.get('model','?')}` | {r.get('papers_evaluated',0)}/{r.get('papers_total',0)} | "
                f"{_fmt_num(r.get('accuracy'))} | {_fmt_num(r.get('precision'))} | "
                f"{_fmt_num(r.get('recall'))} | {_fmt_num(r.get('f1'))} | "
                f"${_fmt_num(r.get('avg_cost_per_paper_usd'), 5)} | "
                f"{r.get('avg_latency_ms', 0)} |"
            )
        best = _best_relevance(relevance_runs)
        if best:
            lines.extend([
                "",
                f"**Recommendation:** `{best['model']}` — best F1 "
                f"({_fmt_num(best.get('f1'))}) at "
                f"${_fmt_num(best.get('avg_cost_per_paper_usd'), 5)}/paper.",
            ])
    else:
        lines.append("| _no runs_ | | | | | | | |")
    lines.append("")

    # ---------- Learn ----------
    lines.extend([
        "## Learn",
        "",
        "Profile-update suggestions. Alignment = LLM-as-judge score (1-5) "
        "for similarity vs Sonnet baseline output on the same input.",
        "",
        "| Model | Areas | Hypothesis | Summaries | Style | Overall | Cost | Latency (ms) |",
        "|---|---|---|---|---|---|---|---|",
    ])
    if learn_runs:
        for r in learn_runs:
            lines.append(
                f"| `{r.get('model','?')}` | {_fmt_num(r.get('areas_alignment'))} | "
                f"{_fmt_num(r.get('hypothesis_alignment'))} | "
                f"{_fmt_num(r.get('summaries_alignment'))} | "
                f"{_fmt_num(r.get('learning_style_alignment'))} | "
                f"**{_fmt_num(r.get('overall_alignment'))}** | "
                f"${_fmt_num(r.get('total_cost_usd'), 4)} | "
                f"{r.get('candidate_latency_ms', 0)} |"
            )
        best = _best_learn(learn_runs)
        if best:
            lines.extend([
                "",
                f"**Recommendation:** `{best['model']}` — top overall_alignment "
                f"({_fmt_num(best.get('overall_alignment'))}/5).",
            ])
    else:
        lines.append("| _no runs_ | | | | | | | |")
    lines.append("")

    return "\n".join(lines)


def _fmt_num(v, places: int = 3) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.{places}f}"
    except (TypeError, ValueError):
        return str(v)


def _best_triage(runs: list[dict]) -> dict | None:
    """Best triage = highest worth_my_hours accuracy, ties broken by lowest MAE."""
    judged = [r for r in runs if r.get("worth_my_hours_accuracy") is not None]
    if not judged:
        return None
    return max(
        judged,
        key=lambda r: (
            float(r.get("worth_my_hours_accuracy") or 0),
            -float(r.get("triage_score_mae") or 1.0),
        ),
    )


def _best_lens(runs: list[dict]) -> dict | None:
    judged = [r for r in runs if r.get("lens_alignment_pct") is not None]
    if not judged:
        return None
    return max(judged, key=lambda r: float(r.get("lens_alignment_pct") or 0))


def _best_relevance(runs: list[dict]) -> dict | None:
    judged = [r for r in runs if r.get("f1") is not None]
    if not judged:
        return None
    return max(judged, key=lambda r: float(r.get("f1") or 0))


def _best_learn(runs: list[dict]) -> dict | None:
    judged = [r for r in runs if r.get("overall_alignment") is not None]
    if not judged:
        return None
    return max(judged, key=lambda r: float(r.get("overall_alignment") or 0))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="eval_pipeline_steps",
        description="Sarathi LLM eval harness for triage / lens / relevance / learn.",
    )
    p.add_argument("--table", default=TABLE_NAME_DEFAULT, help="DDB table name")
    p.add_argument("--region", default=REGION_DEFAULT, help="AWS region")
    sub = p.add_subparsers(dest="cmd", required=True)

    # triage
    sp = sub.add_parser("triage", help="Run triage eval")
    sp.add_argument("--model", default=DEFAULT_MODEL_ID)
    sp.add_argument("--workers", type=int, default=5)
    sp.set_defaults(func=cmd_triage)

    # lens
    sp = sub.add_parser("lens", help="Run lens eval")
    sp.add_argument("--model", default=DEFAULT_MODEL_ID)
    sp.add_argument("--judge-model", default=DEFAULT_MODEL_ID)
    sp.add_argument("--workers", type=int, default=5)
    sp.add_argument("--skip-judge", action="store_true",
                    help="Skip the per-paper reasoning coherence judge")
    sp.set_defaults(func=cmd_lens)

    # relevance
    sp = sub.add_parser("relevance", help="Run relevance filter eval")
    sp.add_argument("--model", default=DEFAULT_MODEL_ID)
    sp.add_argument("--batch-size", type=int, default=25)
    sp.set_defaults(func=cmd_relevance)

    # learn
    sp = sub.add_parser("learn", help="Run learn eval")
    sp.add_argument("--model", default=DEFAULT_MODEL_ID)
    sp.add_argument("--baseline-model", default=DEFAULT_MODEL_ID,
                    help="Model used as the golden Sonnet baseline (default: Sonnet 4.6)")
    sp.add_argument("--judge-model", default=DEFAULT_MODEL_ID)
    sp.set_defaults(func=cmd_learn)

    # all
    sp = sub.add_parser("all", help="Run all 4 step evals for one or more models")
    sp.add_argument("--models", required=True,
                    help="Comma-separated list of model IDs")
    sp.add_argument("--judge-model", default=DEFAULT_MODEL_ID)
    sp.add_argument("--baseline-model", default=DEFAULT_MODEL_ID)
    sp.add_argument("--workers", type=int, default=5)
    sp.add_argument("--batch-size", type=int, default=25)
    sp.add_argument("--skip-judge", action="store_true")
    sp.set_defaults(func=cmd_all)

    # report
    sp = sub.add_parser("report", help="Consolidate all eval results into markdown")
    sp.add_argument("--output", "-o",
                    help="Output path (default: sarathi_eval_pipeline_steps_<timestamp>.md)")
    sp.set_defaults(func=cmd_report)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

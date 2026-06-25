"""LLM evaluation pipeline for Sarathi.

A reusable harness for comparing alternative models against the Sonnet 4.6
baseline on the digest task. Uses the live user's real engagement as the
golden dataset.

Usage:
    AWS_PROFILE=poc python scripts/eval_pipeline.py setup
    AWS_PROFILE=poc python scripts/eval_pipeline.py run --model us.anthropic.claude-haiku-4-5
    AWS_PROFILE=poc python scripts/eval_pipeline.py reset
    AWS_PROFILE=poc python scripts/eval_pipeline.py judge --candidate <run_id>
    AWS_PROFILE=poc python scripts/eval_pipeline.py judge --self-validate
    AWS_PROFILE=poc python scripts/eval_pipeline.py report

Subcommands:
    setup       Clone profile from live user → test user, build eval dataset.
    run         Generate cards for the eval set with the given model.
    reset       Wipe test user paper data (keep profile + conversations).
    judge       LLM-as-judge: score candidate cards vs golden + check engagement alignment.
    report      Print comparison table across all completed runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# Make `backend` importable when this script is invoked directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from backend.eval import dataset as eval_dataset
from backend.eval import judge as judge_mod
from backend.eval import report as report_mod
from backend.eval import runner as runner_mod
from backend.shared.llm import DEFAULT_MODEL_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eval_pipeline")


# ---------------------------------------------------------------------------
# Defaults — override via env vars or CLI flags
# ---------------------------------------------------------------------------

TABLE_NAME_DEFAULT = os.environ.get("SARATHI_TABLE", "sarathi")
S3_BUCKET_DEFAULT = os.environ.get("SARATHI_BUCKET", "sarathi-123456789012-us-east-1")
REGION_DEFAULT = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def _get_table(table_name: str, region: str):
    session = boto3.Session(region_name=region)
    return session.resource("dynamodb").Table(table_name)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_setup(args) -> int:
    """Clone profile + build/persist eval dataset from live user."""
    table = _get_table(args.table, args.region)

    logger.info("=" * 60)
    logger.info("STEP 1: Cloning profile %s -> %s", eval_dataset.LIVE_USER_ID, eval_dataset.TEST_USER_ID)
    logger.info("=" * 60)
    summary = eval_dataset.clone_profile(table)
    logger.info("Profile clone summary: %s", summary)

    logger.info("=" * 60)
    logger.info("STEP 2: Building eval dataset from live user's digested papers")
    logger.info("=" * 60)
    entries = eval_dataset.build_dataset_entries(table, limit=args.limit)
    if not entries:
        logger.error("No digested papers found on live user — nothing to evaluate.")
        return 1

    count = eval_dataset.persist_dataset(table, entries)
    logger.info("=" * 60)
    logger.info("Eval dataset ready: %d papers persisted under EVAL#DATASET", count)
    logger.info("=" * 60)

    # Distribution of engagement labels for sanity
    from collections import Counter
    labels = Counter(judge_mod.actual_engagement_label(e.get("engagement") or {}) for e in entries)
    logger.info("Engagement distribution: %s", dict(labels))
    return 0


def cmd_reset(args) -> int:
    """Wipe test user paper data (keep profile)."""
    table = _get_table(args.table, args.region)
    deleted = runner_mod.reset_test_user(table)
    logger.info("Reset complete: %d items deleted", deleted)
    return 0


def cmd_run(args) -> int:
    """Run digest with the candidate model on every paper in the eval set."""
    table = _get_table(args.table, args.region)

    if args.reset_first:
        deleted = runner_mod.reset_test_user(table)
        logger.info("Pre-run reset: %d items deleted", deleted)

    summary = runner_mod.run_eval(
        table,
        model=args.model,
        s3_bucket=args.bucket,
        max_workers=args.workers,
    )
    logger.info("Run summary: %s", json.dumps(_jsonable(summary), indent=2))
    return 0 if summary.get("papers_succeeded", 0) > 0 else 1


def cmd_judge(args) -> int:
    """LLM-as-judge: score candidate vs golden + check engagement alignment."""
    table = _get_table(args.table, args.region)

    if args.self_validate:
        logger.info("Running self-validation: judging golden vs golden")
        result = judge_mod.run_judge(
            table,
            candidate_run_id="SELF",
            judge_model=args.judge_model,
            self_validation=True,
            seed=args.seed,
        )
        logger.info("Self-validation result: %s", json.dumps(_jsonable(result), indent=2))
        align = result.get("golden", {}).get("engagement_alignment_pct", 0.0)
        if align < 70.0:
            logger.error(
                "Self-validation alignment %.1f%% is below 70%% — judge prompt unreliable.",
                align,
            )
            return 1
        logger.info("Self-validation OK (alignment %.1f%%)", align)
        return 0

    if not args.candidate:
        logger.error("Must pass --candidate <run_id> or --self-validate")
        return 1

    result = judge_mod.run_judge(
        table,
        candidate_run_id=args.candidate,
        judge_model=args.judge_model,
        seed=args.seed,
    )
    logger.info("Judge result: %s", json.dumps(_jsonable(result), indent=2))
    return 0


def cmd_report(args) -> int:
    """Print comparison table across runs and write a markdown file."""
    from datetime import datetime, timezone
    from pathlib import Path

    table = _get_table(args.table, args.region)
    rows = report_mod.build_report_rows(table)

    # Always print to stdout
    print(report_mod.render_report(rows))

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        # Auto-generate: sarathi_eval_<model>_<timestamp>.md
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        # Use the first non-baseline model name, or "all" if multiple
        candidate_rows = [r for r in rows if r.get("judged")]
        if candidate_rows:
            model_slug = candidate_rows[0]["model"].replace(".", "-").replace("/", "_").split(":")[-1]
        else:
            model_slug = "all"
        output_path = Path(f"sarathi_eval_{model_slug}_{ts}.md")

    md = report_mod.render_markdown(rows)
    output_path.write_text(md)
    print(f"\nReport written to: {output_path}")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="eval_pipeline",
        description="Sarathi LLM eval harness — compare models on the digest task.",
    )
    p.add_argument("--table", default=TABLE_NAME_DEFAULT, help="DDB table name")
    p.add_argument("--bucket", default=S3_BUCKET_DEFAULT, help="S3 bucket for paper full text")
    p.add_argument("--region", default=REGION_DEFAULT, help="AWS region")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("setup", help="Clone profile + build eval dataset")
    sp.add_argument("--limit", type=int, default=200, help="Max papers to include")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("reset", help="Wipe test user paper data (keep profile)")
    sp.set_defaults(func=cmd_reset)

    sp = sub.add_parser("run", help="Run digest with a candidate model")
    sp.add_argument(
        "--model", default=DEFAULT_MODEL_ID,
        help="Bedrock model ID (e.g., us.anthropic.claude-haiku-4-5)",
    )
    sp.add_argument("--workers", type=int, default=5, help="Concurrent digest calls")
    sp.add_argument(
        "--reset-first", action="store_true", default=True,
        help="Reset test user paper data before running (default: True)",
    )
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("judge", help="LLM-as-judge: score candidate vs golden")
    sp.add_argument("--candidate", help="Run ID to judge (omit if --self-validate)")
    sp.add_argument(
        "--judge-model", default=judge_mod.JUDGE_DEFAULT_MODEL,
        help="Judge model ID (default: claude-sonnet-4-6)",
    )
    sp.add_argument(
        "--self-validate", action="store_true",
        help="Judge golden vs golden to validate the judge prompt",
    )
    sp.add_argument("--seed", type=int, default=42, help="RNG seed for A/B order randomization")
    sp.set_defaults(func=cmd_judge)

    sp = sub.add_parser("report", help="Print comparison table across runs + write markdown")
    sp.add_argument(
        "--output", "-o",
        help="Output path for markdown report (default: sarathi_eval_<model>_<timestamp>.md)",
    )
    sp.set_defaults(func=cmd_report)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

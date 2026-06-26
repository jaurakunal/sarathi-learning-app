"""End-to-end eval wrapper — run digest with a model, judge it, generate report.

Usage:
    AWS_PROFILE=poc python scripts/eval_full.py --model us.zai.glm-5
    AWS_PROFILE=poc python scripts/eval_full.py --model us.moonshotai.kimi-k2.5 --judge-model us.anthropic.claude-opus-4-7
    AWS_PROFILE=poc python scripts/eval_full.py --model <model> --output my_report.md

This wraps the eval_pipeline.py CLI:
    1. reset (wipe test user paper data)
    2. run (digest all eval-set papers with --model)
    3. judge (LLM-as-judge, candidate vs golden)
    4. report (print + write markdown)

For self-validation (Sonnet judging Sonnet against itself):
    AWS_PROFILE=poc python scripts/eval_full.py --model us.anthropic.claude-sonnet-4-6 --self-validate
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Ensure backend is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import boto3

from backend.eval import dataset, runner as runner_mod, judge as judge_mod, report as report_mod
from backend.shared.llm import DEFAULT_MODEL_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("eval_full")

TABLE_NAME_DEFAULT = os.environ.get("SARATHI_TABLE_NAME", "sarathi")
S3_BUCKET_DEFAULT = os.environ.get("SARATHI_BUCKET", "sarathi-123456789012-us-east-1")
REGION_DEFAULT = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="eval_full",
        description="End-to-end eval: reset → run → judge → report (in one command).",
    )
    parser.add_argument(
        "--model", required=True,
        help="Bedrock model ID to evaluate (e.g., us.zai.glm-5)",
    )
    parser.add_argument(
        "--judge-model", default=judge_mod.JUDGE_DEFAULT_MODEL,
        help=f"Judge model ID (default: {judge_mod.JUDGE_DEFAULT_MODEL})",
    )
    parser.add_argument("--workers", type=int, default=5, help="Concurrent digest calls")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for A/B order")
    parser.add_argument(
        "--self-validate", action="store_true",
        help="Self-validation: judge golden vs golden (use this on Sonnet first)",
    )
    parser.add_argument(
        "--skip-run", action="store_true",
        help="Skip the run step (use existing latest run for this model)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output path for markdown report (default: auto-generated)",
    )
    parser.add_argument("--table", default=TABLE_NAME_DEFAULT, help="DDB table name")
    parser.add_argument("--bucket", default=S3_BUCKET_DEFAULT, help="S3 bucket")
    parser.add_argument("--region", default=REGION_DEFAULT, help="AWS region")

    args = parser.parse_args()

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    started = time.time()

    print(f"\n{'='*70}")
    print(f"  Sarathi Eval — {args.model}")
    print(f"  Judge: {args.judge_model}")
    print(f"{'='*70}\n")

    # Step 1: Run (or skip)
    if args.skip_run:
        # Find latest run for this model
        existing_runs = [r for r in runner_mod.list_runs(table) if r.get("model") == args.model]
        if not existing_runs:
            print(f"❌ --skip-run requested but no existing run found for {args.model}")
            return 1
        run_id = existing_runs[-1]["run_id"]
        print(f"▶ Skipping run; using existing run_id={run_id}")
    else:
        # Reset + run
        print(f"▶ Step 1/3: Reset test user data...")
        runner_mod.reset_test_user(table)

        print(f"▶ Step 2/3: Running digest with {args.model}...")
        run_summary = runner_mod.run_eval(
            table,
            s3_bucket=args.bucket,
            model=args.model,
            max_workers=args.workers,
        )
        run_id = run_summary["run_id"]
        print(f"  ✓ Run complete: {run_summary['papers_succeeded']}/{run_summary['papers_total']} papers succeeded")
        print(f"  ✓ Avg cost/paper: ${run_summary.get('avg_cost_per_paper_usd', 0):.4f}")
        print(f"  ✓ Avg latency: {run_summary.get('avg_latency_ms', 0)} ms")

    # Step 2: Judge
    step = "3/3" if not args.skip_run else "2/2"
    print(f"\n▶ Step {step}: LLM-as-judge ({args.judge_model})...")

    if args.self_validate:
        judge_result = judge_mod.run_judge(
            table,
            candidate_run_id="SELF",
            judge_model=args.judge_model,
            seed=args.seed,
            self_validation=True,
        )
        print(f"  ✓ Self-validation complete (golden vs golden)")
        gold = judge_result.get("golden", {})
        print(f"  Avg scores — Relev: {gold.get('avg_relevance', 0):.2f}, "
              f"Specif: {gold.get('avg_specificity', 0):.2f}, "
              f"Calib: {gold.get('avg_calibration', 0):.2f}, "
              f"Action: {gold.get('avg_actionability', 0):.2f}")
        align = judge_result.get('engagement_alignment_pct', gold.get('engagement_alignment_pct', 0))
        print(f"  Engagement alignment (informational only): {align:.1f}%")
    else:
        judge_result = judge_mod.run_judge(
            table,
            candidate_run_id=run_id,
            judge_model=args.judge_model,
            seed=args.seed,
        )
        print(f"  ✓ Judging complete")
        cand = judge_result.get("candidate", {})
        print(f"  Candidate scores — Relev: {cand.get('avg_relevance', 0):.2f}, "
              f"Specif: {cand.get('avg_specificity', 0):.2f}, "
              f"Calib: {cand.get('avg_calibration', 0):.2f}, "
              f"Action: {cand.get('avg_actionability', 0):.2f}")
        print(f"  Win rate vs baseline: {judge_result.get('win_rate_pct', 0):.1f}%")
        print(f"  Engagement alignment: {judge_result.get('engagement_alignment_pct', 0):.1f}%")

    # Step 3: Report
    print(f"\n▶ Generating report...")
    rows = report_mod.build_report_rows(table)
    print("\n" + report_mod.render_report(rows))

    # Write markdown
    if args.output:
        output_path = Path(args.output)
    else:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        model_slug = args.model.replace(".", "-").replace("/", "_").split(":")[-1]
        output_path = Path(f"sarathi_eval_{model_slug}_{ts}.md")

    md = report_mod.render_markdown(rows)
    output_path.write_text(md)

    elapsed = time.time() - started
    print(f"\n✓ Done in {elapsed:.1f}s")
    print(f"✓ Report written to: {output_path.absolute()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

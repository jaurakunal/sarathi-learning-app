"""Run full eval (digest + judge) N times per model to measure model variance.

Usage:
    AWS_PROFILE=poc python scripts/eval_full_replicate.py
    AWS_PROFILE=poc python scripts/eval_full_replicate.py --runs 3 --models zai.glm-5,moonshotai.kimi-k2.5

For each model:
    For i in range(N):
        reset test user data
        run digest with model on the eval set
        judge candidate cards vs golden with Opus 4.8

Reports mean ± stdev across the N runs per model on:
    relevance, specificity, calibration, actionability, win_rate, cost/paper, latency
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from statistics import mean, stdev

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import boto3
from backend.eval import judge as judge_mod
from backend.eval import runner as runner_mod

JUDGE_MODEL = "us.anthropic.claude-opus-4-8"
S3_BUCKET = "sarathi-123456789012-us-east-1"

DEFAULT_MODELS = [
    "us.anthropic.claude-sonnet-4-6",
    "zai.glm-5",
    "moonshotai.kimi-k2.5",
    "qwen.qwen3-vl-235b-a22b",
    "deepseek.v3.2",
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3, help="Number of runs per model")
    p.add_argument("--models", default=",".join(DEFAULT_MODELS),
                   help="Comma-separated model IDs")
    p.add_argument("--seed", type=int, default=42, help="Judge seed (held constant — model variance only)")
    args = p.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    table = boto3.resource("dynamodb", region_name="us-east-1").Table("sarathi")

    # results[model] = list of {relev, specif, calib, action, win_rate, cost, latency}
    results: dict[str, list[dict]] = {m: [] for m in models}
    started_at = time.time()

    for model in models:
        print(f"\n{'='*70}")
        print(f"  MODEL: {model}")
        print(f"{'='*70}")

        for i in range(args.runs):
            print(f"\n  Run {i+1}/{args.runs} for {model}...")
            print(f"    [1/3] Reset test user data...")
            runner_mod.reset_test_user(table)

            print(f"    [2/3] Running digest with {model}...")
            run_summary = runner_mod.run_eval(
                table,
                s3_bucket=S3_BUCKET,
                model=model,
                max_workers=5,
            )
            run_id = run_summary["run_id"]
            print(f"      ✓ {run_summary['papers_succeeded']}/{run_summary['papers_total']} papers, "
                  f"${run_summary.get('avg_cost_per_paper_usd', 0):.4f}/paper, "
                  f"{run_summary.get('avg_latency_ms', 0)}ms latency")

            print(f"    [3/3] Judging with {JUDGE_MODEL}...")
            judge_result = judge_mod.run_judge(
                table,
                candidate_run_id=run_id,
                judge_model=JUDGE_MODEL,
                seed=args.seed,
            )
            cand = judge_result.get("candidate", {})
            scores = {
                "relev": cand.get("avg_relevance", 0),
                "specif": cand.get("avg_specificity", 0),
                "calib": cand.get("avg_calibration", 0),
                "action": cand.get("avg_actionability", 0),
                "win_rate": judge_result.get("candidate_win_rate_pct", 0),
                "cost": run_summary.get("avg_cost_per_paper_usd", 0),
                "latency": run_summary.get("avg_latency_ms", 0),
                "papers_ok": run_summary.get("papers_succeeded", 0),
            }
            results[model].append(scores)
            print(f"      ✓ Relev: {scores['relev']:.2f}, Specif: {scores['specif']:.2f}, "
                  f"Calib: {scores['calib']:.2f}, Action: {scores['action']:.2f}, "
                  f"Win%: {scores['win_rate']:.1f}")

    # Print summary
    elapsed = time.time() - started_at
    print(f"\n\n{'='*100}")
    print(f"  SUMMARY — Model variance over {args.runs} runs (Opus 4.8 judge, seed={args.seed})")
    print(f"  Total elapsed: {elapsed/60:.1f} min")
    print(f"{'='*100}\n")

    headers = ["Model", "Relev (μ±σ)", "Specif (μ±σ)", "Calib (μ±σ)", "Action (μ±σ)",
               "Win% (μ±σ)", "$/paper (μ)", "Latency (μ)"]
    print(f"{headers[0]:<35} {headers[1]:<15} {headers[2]:<15} {headers[3]:<15} {headers[4]:<15} "
          f"{headers[5]:<15} {headers[6]:<12} {headers[7]:<12}")
    print("-" * 140)

    for model, runs in results.items():
        if not runs:
            print(f"{model:<35}  <no successful runs>")
            continue

        def fmt(vals):
            m = mean(vals)
            s = stdev(vals) if len(vals) > 1 else 0.0
            return f"{m:.2f}±{s:.2f}"

        relev_vals = [r["relev"] for r in runs]
        specif_vals = [r["specif"] for r in runs]
        calib_vals = [r["calib"] for r in runs]
        action_vals = [r["action"] for r in runs]
        win_vals = [r["win_rate"] for r in runs]
        cost_vals = [r["cost"] for r in runs]
        latency_vals = [r["latency"] for r in runs]

        print(f"{model:<35} {fmt(relev_vals):<15} {fmt(specif_vals):<15} "
              f"{fmt(calib_vals):<15} {fmt(action_vals):<15} {fmt(win_vals):<15} "
              f"${mean(cost_vals):.4f}    {int(mean(latency_vals)):>8}ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())

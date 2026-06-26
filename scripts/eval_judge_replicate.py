"""Re-judge existing eval runs N times with different seeds to measure judge variance.

Usage:
    AWS_PROFILE=poc python scripts/eval_judge_replicate.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean, stdev

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import boto3
from backend.eval import judge as judge_mod

JUDGE_MODEL = "us.anthropic.claude-opus-4-8"
SEEDS = [42, 137, 271]  # 3 different seeds for randomized A/B order

# (model_name, latest run_id) — populated from earlier eval runs
RUNS = [
    ("us.anthropic.claude-sonnet-4-6", "2026-06-26T18:15:14.286Z_14f0a7e5"),
    ("zai.glm-5",                       "2026-06-26T18:20:43.987Z_cc68151d"),
    ("moonshotai.kimi-k2.5",            "2026-06-26T18:31:08.169Z_e1ac70fb"),
    ("qwen.qwen3-vl-235b-a22b",         "2026-06-26T18:34:16.660Z_9fa56393"),
    ("deepseek.v3.2",                   "2026-06-26T18:39:52.139Z_94c4d61a"),
]


def main() -> int:
    table = boto3.resource("dynamodb", region_name="us-east-1").Table("sarathi")

    # results[model] = list of {relev, specif, calib, action, win_rate}
    results: dict[str, list[dict]] = {}

    for model, run_id in RUNS:
        print(f"\n{'='*70}")
        print(f"  Replicating judge for: {model}")
        print(f"{'='*70}")
        results[model] = []

        for i, seed in enumerate(SEEDS):
            print(f"  Run {i+1}/3 (seed={seed})...")
            r = judge_mod.run_judge(
                table,
                candidate_run_id=run_id,
                judge_model=JUDGE_MODEL,
                seed=seed,
            )
            cand = r.get("candidate", {})
            scores = {
                "relev": cand.get("avg_relevance", 0),
                "specif": cand.get("avg_specificity", 0),
                "calib": cand.get("avg_calibration", 0),
                "action": cand.get("avg_actionability", 0),
                "win_rate": r.get("candidate_win_rate_pct", 0),
            }
            results[model].append(scores)
            print(f"    Relev: {scores['relev']:.2f}, Specif: {scores['specif']:.2f}, "
                  f"Calib: {scores['calib']:.2f}, Action: {scores['action']:.2f}, "
                  f"Win%: {scores['win_rate']:.1f}")

    # Print summary table
    print(f"\n\n{'='*70}")
    print(f"  SUMMARY — Judge variance under Opus 4.8 (3 seeds)")
    print(f"{'='*70}\n")

    headers = ["Model", "Relev (μ±σ)", "Specif (μ±σ)", "Calib (μ±σ)", "Action (μ±σ)", "Win% (μ±σ)"]
    print(f"{headers[0]:<35} {headers[1]:<15} {headers[2]:<15} {headers[3]:<15} {headers[4]:<15} {headers[5]:<15}")
    print("-" * 110)

    for model, runs in results.items():
        relev_vals = [r["relev"] for r in runs]
        specif_vals = [r["specif"] for r in runs]
        calib_vals = [r["calib"] for r in runs]
        action_vals = [r["action"] for r in runs]
        win_vals = [r["win_rate"] for r in runs]

        def fmt(vals):
            m = mean(vals)
            s = stdev(vals) if len(vals) > 1 else 0.0
            return f"{m:.2f}±{s:.2f}"

        print(f"{model:<35} {fmt(relev_vals):<15} {fmt(specif_vals):<15} "
              f"{fmt(calib_vals):<15} {fmt(action_vals):<15} {fmt(win_vals):<15}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

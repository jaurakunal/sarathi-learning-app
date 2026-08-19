"""Tier 3 eval: independent relevance judge over the FULL candidate pool.

Answers what Tier 2 couldn't: is the pipeline actually selecting the more
relevant papers, and is triage's score calibrated? An independent LLM judge
(different model, blind to triage_score + engagement) scores every candidate —
served or not — for fit to the profile. Then we check:

  1. spearman(triage_score, judge_relevance) over the full pool — does triage
     agree with an independent oracle once we have the full score range (not the
     range-restricted served slice)?
  2. served vs not-served mean judge_relevance — does the pipeline actually
     serve the papers the oracle rates higher?
  3. among served, does judge_relevance predict realized engagement?

Manual/offline. Costs one judge LLM call per paper, so it caps + samples across
the triage-score range to preserve variance.

Usage:
  AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 \
    python -m scripts.eval_relevance_full_pool --user kunaljaura@gmail.com --limit 60
"""

from __future__ import annotations

import argparse
import os
import sys

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.shared import db  # noqa: E402
from backend.eval import learning_metrics as m  # noqa: E402
from backend.eval.eval_common import resolve_sub, as_float, engagement_by_paper  # noqa: E402
from backend.eval.relevance_judge import judge_paper_relevance  # noqa: E402

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
POOL_STATUSES = ("candidate", "surfaced", "digested", "skipped", "rejected")
SERVED_STATUSES = {"digested"}


def _sample_across_range(rows: list[dict], limit: int) -> list[dict]:
    """Keep <=limit rows spread across the triage_score range (preserve variance)."""
    if len(rows) <= limit:
        return rows
    ordered = sorted(rows, key=lambda r: r["triage_score"])
    step = len(ordered) / limit
    return [ordered[int(i * step)] for i in range(limit)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--workspace")
    ap.add_argument("--limit", type=int, default=60, help="max papers to judge (LLM cost)")
    ap.add_argument("--model", help="override the judge model")
    args = ap.parse_args()

    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    sub = resolve_sub(args.user)
    print(f"User: {args.user}  (sub={sub})")

    if args.workspace:
        wids = [args.workspace]
    else:
        wids = [w["workspace_id"] for w in db.list_workspaces(table, sub)
                if w.get("workspace_id") and w.get("status") == "active"]

    for wid in wids:
        profile = db.get_full_profile(table, sub, wid)
        if not profile.get("areas"):
            print(f"\n=== workspace {wid}: no profile areas — skipping ===")
            continue
        profile["user_meta"] = db.get_user_meta(table, sub) or {}

        # Full candidate pool across statuses.
        pool: list[dict] = []
        seen: set[str] = set()
        for status in POOL_STATUSES:
            for p in db.list_papers_by_status(table, sub, wid, status, limit=200):
                pid = p.get("id", "")
                if pid and pid not in seen and "triage_score" in p:
                    seen.add(pid)
                    pool.append(p)

        print(f"\n=== workspace {wid} ===")
        print(f"  candidate pool (scored): {len(pool)}")
        if len(pool) < 5:
            print("  too few scored candidates to judge meaningfully")
            continue

        judged = _sample_across_range(pool, args.limit)
        # Engagement for the served-vs-engagement check.
        eng = engagement_by_paper(table, sub, wid)

        rows = []
        for p in judged:
            r = judge_paper_relevance(p, profile, model=args.model)
            if r["relevance"] is None:
                continue
            pid = p.get("id", "")
            e = eng.get(pid, {"actions": [], "active_ms": 0, "rating": None})
            rows.append({
                "triage_score": as_float(p.get("triage_score")),
                "judge_relevance": r["relevance"],
                "served": p.get("status") in SERVED_STATUSES,
                "engaged": m.label_paper(e["actions"], e["active_ms"], e["rating"]),
            })

        print(f"  judged: {len(rows)} of {len(judged)} sampled")
        if len(rows) < 5:
            print("  too few successful judgements")
            continue

        jr = [r["judge_relevance"] for r in rows]
        print(f"  judge relevance: mean={sum(jr)/len(jr):.3f}  min={min(jr):.3f}  max={max(jr):.3f}")

        # 1. triage vs independent judge (full range)
        rho = m.spearman([r["triage_score"] for r in rows], jr)
        print(f"  spearman(triage_score, judge_relevance): "
              + (f"{rho:+.3f}" if rho is not None else "n/a"))

        # 2. served vs not-served
        served = [r["judge_relevance"] for r in rows if r["served"]]
        notserved = [r["judge_relevance"] for r in rows if not r["served"]]
        if served and notserved:
            ds = sum(served)/len(served)
            dn = sum(notserved)/len(notserved)
            verdict = "GOOD (serves more-relevant)" if ds > dn else "CONCERN (serves less-relevant)"
            print(f"  served mean judge_relevance={ds:.3f} (n={len(served)}) vs "
                  f"not-served={dn:.3f} (n={len(notserved)}) -> {verdict}")
        else:
            print(f"  served vs not-served: not enough of both (served={len(served)}, not={len(notserved)})")

        # 3. among served, does judge relevance predict engagement?
        srv = [r for r in rows if r["served"]]
        if len({r["engaged"] for r in srv}) == 2:
            a = m.auc([r["judge_relevance"] for r in srv], [r["engaged"] for r in srv])
            print(f"  among served, AUC(judge_relevance -> engaged): "
                  + (f"{a:.3f}" if a is not None else "n/a"))

    print("\n--- caveats ---")
    print("  * The judge is an independent LLM oracle conditioned on the profile, a strong")
    print("    second opinion, NOT ground truth. Cross-check its agreement with engagement.")
    print("  * Judge model must differ from triage's (default: Sonnet vs triage's Kimi) and is")
    print("    blind to triage_score + engagement, so the spearman is a fair calibration read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Tier 2 learning-loop eval: does the served paper's triage_score increasingly
predict the engagement the user actually gives it?

Every served paper stores the triage_score it received under the profile that
was current at serve time. If AUC(triage_score -> realized engagement) rises
across a user's tenure, the learning loop is measurably improving relevance —
without reconstructing profiles or calling an LLM, and held-out by construction
(late-tenure triage is scored against engagement that never trained it).

Manual/offline: reads DynamoDB, prints a report. Iterate on methodology here
before automating into a scheduled digest.

Usage:
  AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 \
    python -m scripts.eval_learning_loop --user you@example.com
  ... --user <cognito-sub>                 # sub directly
  ... --user <..> --workspace <wid>        # one workspace (default: all active)
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.shared import db  # noqa: E402
from backend.eval import learning_metrics as m  # noqa: E402

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "us-east-1_XXXXXXXXX")


def _resolve_sub(user: str) -> str:
    """Accept a Cognito sub directly, or resolve an email to its sub."""
    if "@" not in user:
        return user
    cog = boto3.client("cognito-idp")
    resp = cog.list_users(UserPoolId=USER_POOL_ID, Filter=f'email = "{user}"', Limit=1)
    users = resp.get("Users", [])
    if not users:
        raise SystemExit(f"No Cognito user with email {user}")
    return users[0]["Username"]


def _as_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _iso_week(ts: str) -> str:
    """ISO year-week bucket from an ISO timestamp (empty -> 'unknown')."""
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    except (ValueError, AttributeError):
        return "unknown"


def _gather(table, user_id: str, workspace_id: str) -> list[dict]:
    """Build the per-served-paper eval rows for a workspace."""
    # Served papers = feed cards.
    cards: list[dict] = []
    last_key = None
    while True:
        page, last_key = db.list_feed_cards(table, user_id, workspace_id, limit=100, last_key=last_key)
        cards.extend(page)
        if not last_key:
            break

    # Engagement grouped by paper_id.
    events = db.list_all_engagement_events(table, user_id, workspace_id)
    by_paper: dict[str, dict] = defaultdict(lambda: {"actions": [], "active_ms": 0, "rating": None})
    for e in events:
        pid = e.get("paper_id", "")
        if not pid:
            continue
        rec = by_paper[pid]
        action = e.get("action", "")
        if action:
            rec["actions"].append(action)
        rec["active_ms"] = max(rec["active_ms"], int(_as_float(e.get("active_ms"))))
        if e.get("rating") is not None:
            rec["rating"] = int(_as_float(e.get("rating")))

    rows = []
    for card in cards:
        pid = card.get("paper_id", "")
        if not pid:
            continue
        paper = db.get_paper(table, user_id, workspace_id, pid) or {}
        if "triage_score" not in paper:
            continue  # can't evaluate a paper with no score
        eng = by_paper.get(pid, {"actions": [], "active_ms": 0, "rating": None})
        rows.append({
            "paper_id": pid,
            "served_at": card.get("created_at", ""),
            "triage_score": _as_float(paper.get("triage_score")),
            "label": m.label_paper(eng["actions"], eng["active_ms"], eng["rating"]),
        })
    return rows


MIN_ACTIVE_WEEK_N = 5  # min served papers for a week to enter the calibration trend


def _report_block(title: str, rows: list[dict]) -> None:
    print(f"\n=== {title} ===")
    n = len(rows)
    if n == 0:
        print("  no scored served papers")
        return
    scores = [r["triage_score"] for r in rows]
    labels = [r["label"] for r in rows]
    pos = sum(labels)
    print(f"  served (scored): {n}")
    print(f"  engaged (positive): {pos}  ({pos / n:.0%})")
    # Range-restriction guard: triage already filters to its top band before
    # anything is served, so triage_score often barely varies across the served
    # set. When the spread is tiny, AUC is not interpretable as calibration —
    # there's no variance left to rank on. Surface this so the number is never
    # read naively.
    lo, hi = min(scores), max(scores)
    spread = hi - lo
    sd = (sum((s - (sum(scores) / n)) ** 2 for s in scores) / n) ** 0.5
    print(f"  triage_score spread: [{lo:.3f}, {hi:.3f}]  sd={sd:.3f}")
    restricted = sd < 0.10
    a = m.auc(scores, labels)
    if a is not None:
        note = "  (RANGE-RESTRICTED: not interpretable as calibration)" if restricted else ""
        print(f"  overall AUC(triage_score -> engaged): {a:.3f}{note}")
    else:
        print("  overall AUC: n/a (single class)")
    for k in (3, 5, 10):
        p = m.precision_at_k(scores, labels, k)
        nd = m.ndcg_at_k(scores, labels, k)
        if p is not None:
            print(f"  P@{k}={p:.2f}  NDCG@{k}={nd:.2f}" if nd is not None else f"  P@{k}={p:.2f}  NDCG@{k}=n/a")

    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[_iso_week(r["served_at"])].append(r)
    ordered = sorted(w for w in buckets if w != "unknown")

    # ── Axis 1: RETENTION / activity (all weeks) ──────────────────────────
    # Engagement rate over time. A decline here is disengagement, NOT a
    # relevance regression — kept separate so it can't pollute calibration.
    if ordered:
        print("  retention (week: served, engaged%):")
        for w in ordered:
            b = buckets[w]
            bl = [x["label"] for x in b]
            print(f"    {w}: served={len(b):>3}  engaged={sum(bl) / len(bl):.0%}")

    # ── Axis 2: CALIBRATION trend (ACTIVE weeks only) ─────────────────────
    # Does triage_score rank engagement better over time? Only weeks with both
    # engaged and skipped papers (and enough volume) qualify, so inactive weeks
    # don't drag the trend.
    pts = []
    for idx, w in enumerate(ordered):
        bl = [x["label"] for x in buckets[w]]
        if m.is_active_week(bl, MIN_ACTIVE_WEEK_N):
            ba = m.auc([x["triage_score"] for x in buckets[w]], bl)
            pts.append((idx, ba, w, len(bl)))
    if len(pts) >= 2:
        print(f"  calibration trend over {len(pts)} active weeks (week: n, AUC):")
        for _, ba, w, cnt in pts:
            print(f"    {w}: n={cnt:>3}  AUC={ba:.3f}")
        slope = m.trend_slope([(x, y) for x, y, _, _ in pts])
        if slope is not None:
            verdict = "IMPROVING" if slope > 0.01 else ("DECLINING" if slope < -0.01 else "flat")
            print(f"  calibration AUC slope: {slope:+.4f}/active-week  -> {verdict}")
    else:
        print(f"  calibration trend: insufficient active weeks "
              f"(need >=2 with both engaged+skipped and n>={MIN_ACTIVE_WEEK_N})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True, help="Cognito sub or email")
    ap.add_argument("--workspace", help="workspace_id (default: all active)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    sub = _resolve_sub(args.user)
    print(f"User: {args.user}  (sub={sub})")

    if args.workspace:
        wids = [args.workspace]
    else:
        wids = [w["workspace_id"] for w in db.list_workspaces(table, sub)
                if w.get("workspace_id") and w.get("status") == "active"]
    if not wids:
        print("No workspaces to evaluate.")
        return 0

    all_rows: list[dict] = []
    for wid in wids:
        rows = _gather(table, sub, wid)
        all_rows.extend(rows)
        _report_block(f"workspace {wid}", rows)

    if len(wids) > 1:
        _report_block("ALL WORKSPACES (pooled)", all_rows)

    print("\n--- caveats ---")
    print("  * Selection bias: measured only over SERVED papers, not the unseen universe.")
    print("  * Range restriction: triage pre-filters to its top band, so triage_score")
    print("    barely varies across served papers — a compressed spread (sd<0.10) means")
    print("    AUC is NOT a valid read on calibration. Validating triage properly needs")
    print("    scoring the FULL candidate set (Tier 3 LLM judge / interleaving), not just")
    print("    what was served.")
    print("  * Labels are behavioral and noisy; trust the multi-week TREND over any single number.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

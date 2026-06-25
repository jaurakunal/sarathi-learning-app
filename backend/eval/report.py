"""Tabular report comparing eval runs.

Pulls all EVAL#RUN#* META and EVAL#JUDGE#* META records and joins them
into a single comparison table. Prefers `rich` for a colored layout if
available; falls back to plain ASCII otherwise.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.eval import judge as judge_mod
from backend.eval import runner as runner_mod
from backend.shared.llm import DEFAULT_MODEL_ID

logger = logging.getLogger(__name__)


_BASELINE_MODEL = DEFAULT_MODEL_ID


def _coerce_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def build_report_rows(table) -> list[dict]:
    """Build report rows joining run summaries with judge summaries.

    Each row corresponds to a single eval run. If multiple judge runs exist
    against the same candidate, the most recent judge_run_id wins.
    """
    runs = runner_mod.list_runs(table)
    judges = judge_mod.list_judge_runs(table)

    # Index judges by candidate_run_id (latest wins — list is sorted ascending)
    judge_by_candidate: dict[str, dict] = {}
    for j in judges:
        cand = j.get("candidate_run_id", "")
        if cand and cand != "SELF":
            judge_by_candidate[cand] = j

    rows: list[dict] = []
    for r in runs:
        run_id = r.get("run_id", "")
        j = judge_by_candidate.get(run_id) or {}
        cand_block = j.get("candidate") or {}
        gold_block = j.get("golden") or {}

        rows.append({
            "run_id": run_id,
            "model": r.get("model", ""),
            "papers_succeeded": int(_coerce_float(r.get("papers_succeeded"))),
            "papers_total": int(_coerce_float(r.get("papers_total"))),
            "avg_cost_per_paper_usd": _coerce_float(r.get("avg_cost_per_paper_usd")),
            "total_cost_usd": _coerce_float(r.get("total_cost_usd")),
            "avg_latency_ms": int(_coerce_float(r.get("avg_latency_ms"))),
            "avg_relevance": _coerce_float(cand_block.get("avg_relevance")),
            "avg_specificity": _coerce_float(cand_block.get("avg_specificity")),
            "avg_calibration": _coerce_float(cand_block.get("avg_calibration")),
            "avg_actionability": _coerce_float(cand_block.get("avg_actionability")),
            "engagement_alignment_pct": _coerce_float(
                cand_block.get("engagement_alignment_pct")
            ),
            "win_rate_pct": _coerce_float(j.get("candidate_win_rate_pct")),
            "judge_model": j.get("judge_model", ""),
            "golden_alignment_pct": _coerce_float(
                gold_block.get("engagement_alignment_pct")
            ),
            "judged": bool(j),
        })
    return rows


def _winner_indices(rows: list[dict]) -> dict[str, set[int]]:
    """For each metric, return the set of row indices that hold the max value.
    Used to highlight winners in the rendered table.
    """
    metrics = (
        "avg_relevance", "avg_specificity", "avg_calibration",
        "avg_actionability", "engagement_alignment_pct", "win_rate_pct",
    )
    winners: dict[str, set[int]] = {m: set() for m in metrics}
    # Min-cost is also a "win"
    cost_winners: set[int] = set()

    if not rows:
        return {**winners, "avg_cost_per_paper_usd": cost_winners}

    judged_rows = [(i, r) for i, r in enumerate(rows) if r.get("judged")]
    if judged_rows:
        for m in metrics:
            best = max(r[m] for _, r in judged_rows)
            if best > 0:
                winners[m] = {i for i, r in judged_rows if r[m] == best}

    cost_rows = [(i, r) for i, r in enumerate(rows) if r["avg_cost_per_paper_usd"] > 0]
    if cost_rows:
        best_cost = min(r["avg_cost_per_paper_usd"] for _, r in cost_rows)
        cost_winners = {i for i, r in cost_rows if r["avg_cost_per_paper_usd"] == best_cost}

    return {**winners, "avg_cost_per_paper_usd": cost_winners}


def render_report(rows: list[dict]) -> str:
    """Render the report as text. Uses `rich` if installed, else plain ASCII."""
    if not rows:
        return "No eval runs yet. Run `python scripts/eval_pipeline.py run --model <id>` first."

    try:
        from rich.console import Console
        from rich.table import Table
        return _render_rich(rows)
    except ImportError:
        return _render_plain(rows)


def _render_rich(rows: list[dict]) -> str:
    from io import StringIO
    from rich.console import Console
    from rich.table import Table

    winners = _winner_indices(rows)
    table = Table(title="Sarathi Eval — Model Comparison", show_lines=False)
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Papers")
    table.add_column("Relev.", justify="right")
    table.add_column("Specif.", justify="right")
    table.add_column("Calib.", justify="right")
    table.add_column("Action.", justify="right")
    table.add_column("Eng. Align %", justify="right")
    table.add_column("Win Rate %", justify="right")
    table.add_column("$/paper", justify="right")
    table.add_column("Latency ms", justify="right")

    def _fmt(value: float, idx: int, col: str) -> str:
        s = f"{value:.2f}" if isinstance(value, float) else str(value)
        if idx in winners.get(col, set()):
            return f"[bold green]{s}[/bold green]"
        return s

    for i, r in enumerate(rows):
        if not r.get("judged"):
            relev = specif = calib = action = align = win = "[dim]-[/dim]"
        else:
            relev = _fmt(r["avg_relevance"], i, "avg_relevance")
            specif = _fmt(r["avg_specificity"], i, "avg_specificity")
            calib = _fmt(r["avg_calibration"], i, "avg_calibration")
            action = _fmt(r["avg_actionability"], i, "avg_actionability")
            align = _fmt(r["engagement_alignment_pct"], i, "engagement_alignment_pct")
            win = _fmt(r["win_rate_pct"], i, "win_rate_pct")

        cost_str = f"${r['avg_cost_per_paper_usd']:.4f}" if r["avg_cost_per_paper_usd"] else "-"
        if i in winners.get("avg_cost_per_paper_usd", set()):
            cost_str = f"[bold green]{cost_str}[/bold green]"

        table.add_row(
            r["model"],
            f"{r['papers_succeeded']}/{r['papers_total']}",
            relev, specif, calib, action,
            align, win,
            cost_str,
            f"{r['avg_latency_ms']}",
        )

    buf = StringIO()
    Console(file=buf, force_terminal=False, width=140).print(table)
    return buf.getvalue()


def _render_plain(rows: list[dict]) -> str:
    headers = [
        "Model", "Papers", "Relev.", "Specif.", "Calib.",
        "Action.", "Align%", "Win%", "$/paper", "Latency",
    ]
    out_rows: list[list[str]] = [headers]
    for r in rows:
        if not r.get("judged"):
            relev = specif = calib = action = align = win = "-"
        else:
            relev = f"{r['avg_relevance']:.2f}"
            specif = f"{r['avg_specificity']:.2f}"
            calib = f"{r['avg_calibration']:.2f}"
            action = f"{r['avg_actionability']:.2f}"
            align = f"{r['engagement_alignment_pct']:.1f}"
            win = f"{r['win_rate_pct']:.1f}"
        cost_str = f"${r['avg_cost_per_paper_usd']:.4f}" if r["avg_cost_per_paper_usd"] else "-"
        out_rows.append([
            r["model"],
            f"{r['papers_succeeded']}/{r['papers_total']}",
            relev, specif, calib, action,
            align, win,
            cost_str,
            f"{r['avg_latency_ms']}",
        ])

    widths = [max(len(row[i]) for row in out_rows) for i in range(len(headers))]
    lines = []
    for ri, row in enumerate(out_rows):
        line = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        lines.append(line)
        if ri == 0:
            lines.append("-" * len(line))
    return "Sarathi Eval — Model Comparison\n" + "\n".join(lines)

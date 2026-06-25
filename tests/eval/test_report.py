"""Tests for backend.eval.report — table joining + rendering."""

from __future__ import annotations

from backend.eval import report as report_mod


def test_render_report_handles_empty_runs(fake_table):
    rows = report_mod.build_report_rows(fake_table)
    out = report_mod.render_report(rows)
    assert "No eval runs yet" in out


def test_build_report_rows_joins_run_with_judge(fake_table):
    """Each run row picks up its candidate judge metrics."""
    fake_table.put_item(Item={
        "PK": "EVAL#RUN#run-1",
        "SK": "META",
        "run_id": "run-1",
        "model": "us.anthropic.claude-haiku-4-5",
        "started_at": "2026-06-25T12:00:00Z",
        "papers_total": 5,
        "papers_succeeded": 5,
        "avg_cost_per_paper_usd": 0.01,
        "total_cost_usd": 0.05,
        "avg_latency_ms": 4500,
    })
    fake_table.put_item(Item={
        "PK": "EVAL#JUDGE#judge-1",
        "SK": "META",
        "judge_run_id": "judge-1",
        "candidate_run_id": "run-1",
        "judge_model": "us.anthropic.claude-sonnet-4-6",
        "completed_at": "2026-06-25T13:00:00Z",
        "candidate": {
            "avg_relevance": 4.0,
            "avg_specificity": 3.5,
            "avg_calibration": 4.5,
            "avg_actionability": 4.0,
            "engagement_alignment_pct": 80.0,
        },
        "golden": {
            "avg_relevance": 4.5,
            "engagement_alignment_pct": 90.0,
        },
        "candidate_win_rate_pct": 40.0,
    })

    rows = report_mod.build_report_rows(fake_table)
    assert len(rows) == 1
    r = rows[0]
    assert r["model"] == "us.anthropic.claude-haiku-4-5"
    assert r["judged"] is True
    assert r["avg_relevance"] == 4.0
    assert r["engagement_alignment_pct"] == 80.0
    assert r["win_rate_pct"] == 40.0


def test_build_report_rows_unjudged_run(fake_table):
    """A run without a matching judge entry shows judged=False."""
    fake_table.put_item(Item={
        "PK": "EVAL#RUN#run-2",
        "SK": "META",
        "run_id": "run-2",
        "model": "us.anthropic.claude-opus-4-7",
        "started_at": "2026-06-25T12:00:00Z",
        "papers_total": 3,
        "papers_succeeded": 3,
        "avg_cost_per_paper_usd": 0.05,
    })

    rows = report_mod.build_report_rows(fake_table)
    assert len(rows) == 1
    assert rows[0]["judged"] is False
    assert rows[0]["avg_relevance"] == 0.0


def test_winner_indices_ignores_unjudged():
    """Winner detection skips rows that haven't been judged."""
    rows = [
        {"avg_relevance": 4.0, "avg_specificity": 4.0, "avg_calibration": 4.0,
         "avg_actionability": 4.0, "engagement_alignment_pct": 80.0,
         "win_rate_pct": 50.0, "avg_cost_per_paper_usd": 0.01, "judged": True},
        {"avg_relevance": 3.0, "avg_specificity": 3.0, "avg_calibration": 3.0,
         "avg_actionability": 3.0, "engagement_alignment_pct": 60.0,
         "win_rate_pct": 30.0, "avg_cost_per_paper_usd": 0.05, "judged": True},
        {"avg_relevance": 0.0, "avg_specificity": 0.0, "avg_calibration": 0.0,
         "avg_actionability": 0.0, "engagement_alignment_pct": 0.0,
         "win_rate_pct": 0.0, "avg_cost_per_paper_usd": 0.001, "judged": False},
    ]
    winners = report_mod._winner_indices(rows)
    assert winners["avg_relevance"] == {0}
    # Cheapest is row 2 (unjudged still wins on cost — that's fine)
    assert winners["avg_cost_per_paper_usd"] == {2}


def test_render_plain_includes_headers_and_models(fake_table):
    fake_table.put_item(Item={
        "PK": "EVAL#RUN#run-A",
        "SK": "META",
        "run_id": "run-A",
        "model": "us.anthropic.claude-haiku-4-5",
        "started_at": "2026-06-25T12:00:00Z",
        "papers_total": 1,
        "papers_succeeded": 1,
        "avg_cost_per_paper_usd": 0.01,
    })
    rows = report_mod.build_report_rows(fake_table)
    plain = report_mod._render_plain(rows)
    assert "Model" in plain
    assert "us.anthropic.claude-haiku-4-5" in plain

"""Tests for backend.pipeline.select — the Select pipeline step."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Happy path: 10 surfaced papers, max_cards=5 → top 5 kept, bottom 5 skipped
# ---------------------------------------------------------------------------

@patch("backend.pipeline.select.boto3")
@patch("backend.pipeline.select.db")
def test_happy_path_top_n_selected(mock_db, mock_boto3, user_id, table_name):
    """10 surfaced papers with max_cards=5 — top 5 kept, bottom 5 demoted to skipped."""
    from backend.pipeline.select import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    # Generate 10 surfaced papers with decreasing scores
    papers = []
    for i in range(10):
        papers.append({
            "id": f"paper-{i:03d}",
            "source": "arxiv",
            "title": f"Paper {i}",
            "status": "surfaced",
            "triage_score": Decimal(str(0.95 - i * 0.05)),  # 0.95, 0.90, ..., 0.50
            "worth_my_hours": True,
        })

    mock_db.list_papers_by_status.return_value = papers

    result = handler(
        {"user_id": user_id, "table_name": table_name, "max_cards": 5},
        None,
    )

    assert result["selected"] == 5
    assert result["skipped_over_budget"] == 5
    assert result["dry_week"] is False

    # Only over-budget papers get written (demoted)
    assert mock_db.put_paper.call_count == 5

    # All demoted papers should have status="skipped" and skip_reason
    for call in mock_db.put_paper.call_args_list:
        paper = call[0][3]
        assert paper["status"] == "skipped"
        assert paper["skip_reason"] == "over_time_budget"


# ---------------------------------------------------------------------------
# Under budget: 3 surfaced papers, max_cards=5 → all kept, none skipped
# ---------------------------------------------------------------------------

@patch("backend.pipeline.select.boto3")
@patch("backend.pipeline.select.db")
def test_under_budget_all_kept(mock_db, mock_boto3, user_id, table_name, sample_surfaced_papers):
    """Fewer papers than max_cards — all kept, none demoted."""
    from backend.pipeline.select import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    # 3 papers, max_cards=5
    mock_db.list_papers_by_status.return_value = sample_surfaced_papers

    result = handler(
        {"user_id": user_id, "table_name": table_name, "max_cards": 5},
        None,
    )

    assert result["selected"] == 3
    assert result["skipped_over_budget"] == 0
    assert result["dry_week"] is False

    # No papers should be written (no demotions needed)
    mock_db.put_paper.assert_not_called()


# ---------------------------------------------------------------------------
# Dry week: zero surfaced papers → dry_week=True
# ---------------------------------------------------------------------------

@patch("backend.pipeline.select.boto3")
@patch("backend.pipeline.select.db")
def test_dry_week_no_surfaced_papers(mock_db, mock_boto3, user_id, table_name):
    """Zero surfaced papers → dry_week=True."""
    from backend.pipeline.select import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    mock_db.list_papers_by_status.return_value = []

    result = handler(
        {"user_id": user_id, "table_name": table_name},
        None,
    )

    assert result["selected"] == 0
    assert result["skipped_over_budget"] == 0
    assert result["dry_week"] is True
    mock_db.put_paper.assert_not_called()


# ---------------------------------------------------------------------------
# Sorting: papers are selected by triage_score descending
# ---------------------------------------------------------------------------

@patch("backend.pipeline.select.boto3")
@patch("backend.pipeline.select.db")
def test_sorting_by_triage_score_descending(mock_db, mock_boto3, user_id, table_name):
    """Papers are sorted by triage_score descending — highest scores kept."""
    from backend.pipeline.select import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    # Papers in random score order
    papers = [
        {"id": "low", "status": "surfaced", "triage_score": Decimal("0.3")},
        {"id": "high", "status": "surfaced", "triage_score": Decimal("0.95")},
        {"id": "medium", "status": "surfaced", "triage_score": Decimal("0.6")},
    ]
    mock_db.list_papers_by_status.return_value = papers

    result = handler(
        {"user_id": user_id, "table_name": table_name, "max_cards": 2},
        None,
    )

    assert result["selected"] == 2
    assert result["skipped_over_budget"] == 1

    # The demoted paper should be the lowest-scored one
    demoted_paper = mock_db.put_paper.call_args[0][3]
    assert demoted_paper["id"] == "low"
    assert demoted_paper["status"] == "skipped"


# ---------------------------------------------------------------------------
# Default max_cards is 5
# ---------------------------------------------------------------------------

@patch("backend.pipeline.select.boto3")
@patch("backend.pipeline.select.db")
def test_default_max_cards(mock_db, mock_boto3, user_id, table_name):
    """When max_cards is not provided, default of 5 is used."""
    from backend.pipeline.select import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    # 7 papers, no max_cards in event
    papers = [
        {"id": f"paper-{i}", "status": "surfaced", "triage_score": Decimal(str(0.9 - i * 0.1))}
        for i in range(7)
    ]
    mock_db.list_papers_by_status.return_value = papers

    result = handler(
        {"user_id": user_id, "table_name": table_name},  # No max_cards
        None,
    )

    assert result["selected"] == 5
    assert result["skipped_over_budget"] == 2


# ---------------------------------------------------------------------------
# Verify correct arguments passed to db functions
# ---------------------------------------------------------------------------

@patch("backend.pipeline.select.boto3")
@patch("backend.pipeline.select.db")
def test_db_calls_correct_arguments(mock_db, mock_boto3, user_id, table_name):
    """Verify db.list_papers_by_status and db.put_paper receive correct args."""
    from backend.pipeline.select import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    papers = [
        {"id": "keep", "status": "surfaced", "triage_score": Decimal("0.9")},
        {"id": "demote", "status": "surfaced", "triage_score": Decimal("0.3")},
    ]
    mock_db.list_papers_by_status.return_value = papers

    handler({"user_id": user_id, "table_name": table_name, "max_cards": 1}, None)

    # Verify list_papers_by_status
    mock_db.list_papers_by_status.assert_called_once_with(mock_table, user_id, "", "surfaced")

    # Verify put_paper for the demoted paper
    mock_db.put_paper.assert_called_once()
    args = mock_db.put_paper.call_args[0]
    assert args[0] is mock_table
    assert args[1] == user_id
    assert args[3]["id"] == "demote"


# ---------------------------------------------------------------------------
# Handles Decimal scores from DDB gracefully
# ---------------------------------------------------------------------------

@patch("backend.pipeline.select.boto3")
@patch("backend.pipeline.select.db")
def test_handles_decimal_scores(mock_db, mock_boto3, user_id, table_name):
    """DDB returns Decimal types for triage_score — no crash."""
    from backend.pipeline.select import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_db.get_active_workspace.return_value = ""

    papers = [
        {"id": "p1", "status": "surfaced", "triage_score": Decimal("0.85")},
        {"id": "p2", "status": "surfaced", "triage_score": Decimal("0.42")},
    ]
    mock_db.list_papers_by_status.return_value = papers

    # Should not raise
    result = handler(
        {"user_id": user_id, "table_name": table_name, "max_cards": 1},
        None,
    )

    assert result["selected"] == 1
    assert result["skipped_over_budget"] == 1

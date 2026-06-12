"""Tests for backend.pipeline.discover — the Discover pipeline step."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Happy path: sources return papers, dedup works, new papers written to DDB
# ---------------------------------------------------------------------------

@patch("backend.shared.relevance_filter.call_llm", return_value="[0, 1, 2, 3, 4, 5]")
@patch("backend.shared.query_gen.call_llm", return_value='["test query 1", "test query 2"]')
@patch("backend.pipeline.discover.boto3")
@patch("backend.pipeline.discover.db")
@patch("backend.pipeline.discover.ArxivSource")
@patch("backend.pipeline.discover.SemanticScholarSource")
@patch("backend.pipeline.discover.HFDailyPapersSource")
@patch("backend.pipeline.discover.OpenReviewSource")
def test_happy_path_writes_new_papers(
    MockOR, MockHF, MockSS, MockArxiv, mock_db, mock_boto3,
    user_id, table_name, sample_papers,
):
    """Sources return papers, all new — all written to DDB."""
    from backend.pipeline.discover import handler

    # Setup DDB mock
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    # Profile areas returned
    mock_db.get_profile_areas.return_value = [
        {
            "id": "area-1",
            "user_id": user_id,
            "label": "Memory Architecture",
            "status": "active",
            "role": "spine",
            "links": [],
            "frontier": "episodic memory",
            "too_basic": [],
            "just_right": [],
            "added_at": "2026-06-01T00:00:00Z",
        }
    ]

    # No existing papers
    mock_db.paper_exists.return_value = False

    MockArxiv.return_value.name = "arxiv"
    MockArxiv.return_value.discover.return_value = [sample_papers[0]]

    MockSS.return_value.name = "semantic_scholar"
    MockSS.return_value.discover.return_value = [sample_papers[1]]

    MockHF.return_value.name = "hf_daily_papers"
    MockHF.return_value.discover.return_value = [sample_papers[2]]

    MockOR.return_value.name = "openreview"
    MockOR.return_value.discover.return_value = []

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["candidates_found"] == 3
    assert result["new_candidates_written"] == 3
    assert result["duplicates_skipped"] == 0
    assert mock_db.put_paper.call_count == 3


# ---------------------------------------------------------------------------
# Source failure: one source throws, others still work (error isolation)
# ---------------------------------------------------------------------------

@patch("backend.shared.relevance_filter.call_llm", return_value="[0, 1, 2, 3, 4, 5]")
@patch("backend.shared.query_gen.call_llm", return_value='["test query 1", "test query 2"]')
@patch("backend.pipeline.discover.boto3")
@patch("backend.pipeline.discover.db")
@patch("backend.pipeline.discover.ArxivSource")
@patch("backend.pipeline.discover.SemanticScholarSource")
@patch("backend.pipeline.discover.HFDailyPapersSource")
@patch("backend.pipeline.discover.OpenReviewSource")
def test_source_failure_isolation(
    MockOR, MockHF, MockSS, MockArxiv, mock_db, mock_boto3,
    user_id, table_name, sample_papers,
):
    """One source raises an exception — other sources still contribute papers."""
    from backend.pipeline.discover import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_profile_areas.return_value = [
        {"id": "a1", "user_id": user_id, "label": "Test", "status": "active",
         "role": "spine", "links": [], "frontier": "", "too_basic": [],
         "just_right": [], "added_at": None}
    ]
    mock_db.paper_exists.return_value = False

    MockArxiv.return_value.name = "arxiv"
    MockArxiv.return_value.discover.side_effect = RuntimeError("network timeout")

    MockSS.return_value.name = "semantic_scholar"
    MockSS.return_value.discover.return_value = [sample_papers[1]]

    MockHF.return_value.name = "hf_daily_papers"
    MockHF.return_value.discover.return_value = [sample_papers[2]]

    MockOR.return_value.name = "openreview"
    MockOR.return_value.discover.return_value = []

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    # Arxiv failed but the other 2 papers still got written
    assert result["candidates_found"] == 2
    assert result["new_candidates_written"] == 2


# ---------------------------------------------------------------------------
# Dedup by title: duplicate titles across sources are collapsed
# ---------------------------------------------------------------------------

@patch("backend.shared.relevance_filter.call_llm", return_value="[0, 1, 2, 3, 4, 5]")
@patch("backend.shared.query_gen.call_llm", return_value='["test query 1", "test query 2"]')
@patch("backend.pipeline.discover.boto3")
@patch("backend.pipeline.discover.db")
@patch("backend.pipeline.discover.ArxivSource")
@patch("backend.pipeline.discover.SemanticScholarSource")
@patch("backend.pipeline.discover.HFDailyPapersSource")
@patch("backend.pipeline.discover.OpenReviewSource")
def test_dedup_by_title(
    MockOR, MockHF, MockSS, MockArxiv, mock_db, mock_boto3,
    user_id, table_name,
):
    """Papers with the same title (case-insensitive) across sources are deduplicated."""
    from backend.pipeline.discover import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_profile_areas.return_value = [
        {"id": "a1", "user_id": user_id, "label": "Test", "status": "active",
         "role": "spine", "links": [], "frontier": "", "too_basic": [],
         "just_right": [], "added_at": None}
    ]
    mock_db.paper_exists.return_value = False

    paper_a = {
        "id": "paper-from-arxiv",
        "source": "arxiv",
        "title": "Memory Architecture for Agents",
        "authors": ["Smith"],
        "abstract": "Abstract A",
        "url": "https://arxiv.org/abs/001",
        "published": "2026-06-05",
    }
    paper_b = {
        "id": "paper-from-ss",
        "source": "semantic_scholar",
        "title": "memory architecture for agents",  # Same title, different case
        "authors": ["Smith"],
        "abstract": "Abstract B",
        "url": "https://ss.org/002",
        "published": "2026-06-05",
    }

    MockArxiv.return_value.name = "arxiv"
    MockArxiv.return_value.discover.return_value = [paper_a]

    MockSS.return_value.name = "semantic_scholar"
    MockSS.return_value.discover.return_value = [paper_b]

    MockHF.return_value.name = "hf_daily_papers"
    MockHF.return_value.discover.return_value = []

    MockOR.return_value.name = "openreview"
    MockOR.return_value.discover.return_value = []

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    # Only 1 unique paper after dedup
    assert result["candidates_found"] == 1
    assert result["new_candidates_written"] == 1


# ---------------------------------------------------------------------------
# Already-seen paper: paper_exists returns True → skipped
# ---------------------------------------------------------------------------

@patch("backend.shared.relevance_filter.call_llm", return_value="[0, 1, 2, 3, 4, 5]")
@patch("backend.shared.query_gen.call_llm", return_value='["test query 1", "test query 2"]')
@patch("backend.pipeline.discover.boto3")
@patch("backend.pipeline.discover.db")
@patch("backend.pipeline.discover.ArxivSource")
@patch("backend.pipeline.discover.SemanticScholarSource")
@patch("backend.pipeline.discover.HFDailyPapersSource")
@patch("backend.pipeline.discover.OpenReviewSource")
def test_already_seen_paper_skipped(
    MockOR, MockHF, MockSS, MockArxiv, mock_db, mock_boto3,
    user_id, table_name, sample_papers,
):
    """Papers that already exist in DDB are counted as duplicates_skipped."""
    from backend.pipeline.discover import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_profile_areas.return_value = [
        {"id": "a1", "user_id": user_id, "label": "Test", "status": "active",
         "role": "spine", "links": [], "frontier": "", "too_basic": [],
         "just_right": [], "added_at": None}
    ]

    # First paper already exists, second does not
    mock_db.paper_exists.side_effect = [True, False]

    MockArxiv.return_value.name = "arxiv"
    MockArxiv.return_value.discover.return_value = [sample_papers[0], sample_papers[1]]

    MockSS.return_value.name = "semantic_scholar"
    MockSS.return_value.discover.return_value = []

    MockHF.return_value.name = "hf_daily_papers"
    MockHF.return_value.discover.return_value = []

    MockOR.return_value.name = "openreview"
    MockOR.return_value.discover.return_value = []

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["candidates_found"] == 2
    assert result["new_candidates_written"] == 1
    assert result["duplicates_skipped"] == 1


# ---------------------------------------------------------------------------
# Empty results: all sources return nothing → summary shows zeros
# ---------------------------------------------------------------------------

@patch("backend.shared.relevance_filter.call_llm", return_value="[0, 1, 2, 3, 4, 5]")
@patch("backend.shared.query_gen.call_llm", return_value='["test query 1", "test query 2"]')
@patch("backend.pipeline.discover.boto3")
@patch("backend.pipeline.discover.db")
@patch("backend.pipeline.discover.ArxivSource")
@patch("backend.pipeline.discover.SemanticScholarSource")
@patch("backend.pipeline.discover.HFDailyPapersSource")
@patch("backend.pipeline.discover.OpenReviewSource")
def test_empty_results_all_sources(
    MockOR, MockHF, MockSS, MockArxiv, mock_db, mock_boto3,
    user_id, table_name,
):
    """When all sources return no papers, summary shows zeros."""
    from backend.pipeline.discover import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_profile_areas.return_value = [
        {"id": "a1", "user_id": user_id, "label": "Test", "status": "active",
         "role": "spine", "links": [], "frontier": "", "too_basic": [],
         "just_right": [], "added_at": None}
    ]

    MockArxiv.return_value.name = "arxiv"
    MockArxiv.return_value.discover.return_value = []

    MockSS.return_value.name = "semantic_scholar"
    MockSS.return_value.discover.return_value = []

    MockHF.return_value.name = "hf_daily_papers"
    MockHF.return_value.discover.return_value = []

    MockOR.return_value.name = "openreview"
    MockOR.return_value.discover.return_value = []

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["candidates_found"] == 0
    assert result["new_candidates_written"] == 0
    assert result["duplicates_skipped"] == 0


# ---------------------------------------------------------------------------
# No areas in profile → returns zeros immediately
# ---------------------------------------------------------------------------

@patch("backend.pipeline.discover.boto3")
@patch("backend.pipeline.discover.db")
def test_no_areas_returns_zeros(mock_db, mock_boto3, user_id, table_name):
    """When user has no areas, handler returns zero summary without querying sources."""
    from backend.pipeline.discover import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_profile_areas.return_value = []

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["candidates_found"] == 0
    assert result["new_candidates_written"] == 0
    assert result["duplicates_skipped"] == 0


# ---------------------------------------------------------------------------
# Correct arguments passed to db functions
# ---------------------------------------------------------------------------

@patch("backend.shared.relevance_filter.call_llm", return_value="[0, 1, 2, 3, 4, 5]")
@patch("backend.shared.query_gen.call_llm", return_value='["test query 1", "test query 2"]')
@patch("backend.pipeline.discover.boto3")
@patch("backend.pipeline.discover.db")
@patch("backend.pipeline.discover.ArxivSource")
@patch("backend.pipeline.discover.SemanticScholarSource")
@patch("backend.pipeline.discover.HFDailyPapersSource")
@patch("backend.pipeline.discover.OpenReviewSource")
def test_db_calls_receive_correct_arguments(
    MockOR, MockHF, MockSS, MockArxiv, mock_db, mock_boto3,
    user_id, table_name,
):
    """Verify db functions are called with correct table and user_id arguments."""
    from backend.pipeline.discover import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_profile_areas.return_value = [
        {"id": "a1", "user_id": user_id, "label": "Test", "status": "active",
         "role": "spine", "links": [], "frontier": "", "too_basic": [],
         "just_right": [], "added_at": None}
    ]
    mock_db.paper_exists.return_value = False

    paper = {
        "id": "paper-xyz",
        "source": "arxiv",
        "title": "Test Paper",
        "authors": [],
        "abstract": "abs",
        "url": "http://example.com",
        "published": "2026-06-01",
    }

    MockArxiv.return_value.name = "arxiv"
    MockArxiv.return_value.discover.return_value = [paper]

    MockSS.return_value.name = "semantic_scholar"
    MockSS.return_value.discover.return_value = []

    MockHF.return_value.name = "hf_daily_papers"
    MockHF.return_value.discover.return_value = []

    MockOR.return_value.name = "openreview"
    MockOR.return_value.discover.return_value = []

    handler({"user_id": user_id, "table_name": table_name}, None)

    # Verify get_profile_areas was called with correct args
    mock_db.get_profile_areas.assert_called_once_with(mock_table, user_id)

    # Verify paper_exists was called with table, user_id, paper_id
    mock_db.paper_exists.assert_called_once_with(mock_table, user_id, "paper-xyz")

    # Verify put_paper was called with table, user_id, and a paper record
    mock_db.put_paper.assert_called_once()
    call_args = mock_db.put_paper.call_args
    assert call_args[0][0] is mock_table
    assert call_args[0][1] == user_id
    paper_record = call_args[0][2]
    assert paper_record["id"] == "paper-xyz"
    assert paper_record["status"] == "candidate"
    assert paper_record["triage_score"] == 0
    assert paper_record["worth_my_hours"] is False

"""Tests for the Papers With Code source."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import json

import pytest

from backend.sources.papers_with_code import PapersWithCodeSource



def _days_ago(days: int) -> str:
    """A publication date relative to today, so fixtures never age out of the
    discovery window the tests query with."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


SAMPLE_RESPONSE = {
    "count": 2,
    "results": [
        {
            "id": "memory-augmented-agents",
            "title": "Memory-Augmented Agents for Long Tasks",
            "abstract": "We present a novel memory architecture for long-running agents.",
            "url_abs": "https://arxiv.org/abs/2606.99999",
            "published": _days_ago(2),
            "authors": ["Alice Smith", "Bob Jones"],
        },
        {
            "id": "graph-memory-llm",
            "title": "Graph-Based Memory for LLM Agents",
            "abstract": "We use property graphs as a memory substrate for conversational AI.",
            "url_abs": "https://arxiv.org/abs/2606.88888",
            "published": _days_ago(5),
            "authors": ["Carol White"],
        },
    ],
}


class TestPapersWithCodeSource:
    def test_discover_returns_papers(self):
        source = PapersWithCodeSource()
        since = datetime.now(timezone.utc) - timedelta(days=14)

        with patch("backend.sources.papers_with_code.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = SAMPLE_RESPONSE
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since, queries=["memory agents"])

        assert len(papers) == 2
        assert papers[0]["title"] == "Memory-Augmented Agents for Long Tasks"
        assert papers[0]["source"] == "papers_with_code"
        assert papers[0]["has_code"] is True

    def test_extracts_arxiv_id_from_url(self):
        source = PapersWithCodeSource()
        since = datetime.now(timezone.utc) - timedelta(days=14)

        with patch("backend.sources.papers_with_code.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = SAMPLE_RESPONSE
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since, queries=["test"])

        assert papers[0]["id"] == "2606.99999"
        assert papers[1]["id"] == "2606.88888"

    def test_filters_old_papers(self):
        source = PapersWithCodeSource()
        # Cutoff falls between the two fixture papers (2 and 5 days old).
        since = datetime.now(timezone.utc) - timedelta(days=3)

        with patch("backend.sources.papers_with_code.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = SAMPLE_RESPONSE
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since, queries=["test"])

        # Only the 2-day-old paper should pass (the 5-day-old one is before since)
        assert len(papers) == 1
        assert papers[0]["title"] == "Memory-Augmented Agents for Long Tasks"

    def test_deduplicates_across_queries(self):
        source = PapersWithCodeSource()
        since = datetime.now(timezone.utc) - timedelta(days=14)

        with patch("backend.sources.papers_with_code.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = SAMPLE_RESPONSE
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            # Two queries that return the same results
            papers = source.discover([], since, queries=["memory", "agents"])

        # Should dedupe — same papers from both queries
        assert len(papers) == 2

    def test_handles_api_failure(self):
        import requests as req
        source = PapersWithCodeSource()
        since = datetime.now(timezone.utc) - timedelta(days=14)

        with patch("backend.sources.papers_with_code.requests.get") as mock_get:
            mock_get.side_effect = req.RequestException("API error")
            papers = source.discover([], since, queries=["test"])

        assert papers == []

    def test_handles_empty_results(self):
        source = PapersWithCodeSource()
        since = datetime.now(timezone.utc) - timedelta(days=14)

        with patch("backend.sources.papers_with_code.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"count": 0, "results": []}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since, queries=["obscure topic"])

        assert papers == []

    def test_non_arxiv_paper_gets_pwc_id(self):
        source = PapersWithCodeSource()
        since = datetime.now(timezone.utc) - timedelta(days=14)

        non_arxiv_response = {
            "results": [{
                "id": "some-paper-slug",
                "title": "A Paper Without ArXiv",
                "abstract": "Description",
                "url_abs": "https://paperswithcode.com/paper/some-paper-slug",
                "published": _days_ago(2),
                "authors": [],
            }]
        }

        with patch("backend.sources.papers_with_code.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = non_arxiv_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since, queries=["test"])

        assert papers[0]["id"] == "pwc:some-paper-slug"

    def test_caps_at_10_queries(self):
        source = PapersWithCodeSource()
        since = datetime.now(timezone.utc) - timedelta(days=14)

        call_count = 0

        def mock_get_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"results": []}
            resp.raise_for_status = MagicMock()
            return resp

        with patch("backend.sources.papers_with_code.requests.get", side_effect=mock_get_fn):
            source.discover([], since, queries=[f"query{i}" for i in range(20)])

        assert call_count == 10  # Capped at 10

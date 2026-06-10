"""Comprehensive unit tests for backend.sources.semantic_scholar module."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.shared.models import Area
from backend.sources.semantic_scholar import SemanticScholarSource, _build_queries


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_areas() -> list[Area]:
    return [
        Area(
            id="area1",
            user_id="user1",
            label="mechanistic interpretability",
            just_right=["sparse autoencoders", "circuit analysis"],
            frontier="Scaling SAEs",
        ),
        Area(
            id="area2",
            user_id="user1",
            label="AI alignment",
            just_right=["RLHF"],
            frontier="",
        ),
    ]


@pytest.fixture
def single_area() -> list[Area]:
    return [
        Area(
            id="area1",
            user_id="user1",
            label="reinforcement learning",
            just_right=["PPO", "DPO"],
        ),
    ]


@pytest.fixture
def s2_source() -> SemanticScholarSource:
    return SemanticScholarSource(max_results_per_query=10)


@pytest.fixture
def sample_s2_paper() -> dict:
    """A typical Semantic Scholar API paper object."""
    return {
        "paperId": "abc123def456",
        "title": "Sparse Autoencoders for Interpretability",
        "authors": [
            {"authorId": "1", "name": "Alice Researcher"},
            {"authorId": "2", "name": "Bob Scientist"},
        ],
        "abstract": "We study SAE features in large language models.",
        "url": "https://www.semanticscholar.org/paper/abc123def456",
        "publicationDate": "2024-06-15",
        "fieldsOfStudy": ["Computer Science"],
        "citationCount": 42,
        "influentialCitationCount": 5,
    }


@pytest.fixture
def old_s2_paper() -> dict:
    """A paper published before the since cutoff."""
    return {
        "paperId": "old111old222",
        "title": "Ancient Wisdom",
        "authors": [{"authorId": "3", "name": "Charlie Oldtimer"}],
        "abstract": "This was published long ago.",
        "url": "https://www.semanticscholar.org/paper/old111old222",
        "publicationDate": "2022-01-01",
        "fieldsOfStudy": ["Computer Science"],
        "citationCount": 100,
        "influentialCitationCount": 10,
    }


@pytest.fixture
def s2_api_response(sample_s2_paper) -> dict:
    """A typical S2 search API response with one paper."""
    return {
        "total": 1,
        "offset": 0,
        "data": [sample_s2_paper],
    }


# ─── _build_queries tests ────────────────────────────────────────────────────


class TestBuildQueries:
    def test_multiple_areas(self, sample_areas):
        queries = _build_queries(sample_areas)
        assert len(queries) == 2
        assert "mechanistic interpretability" in queries[0]
        assert "sparse autoencoders" in queries[0]
        assert "circuit analysis" in queries[0]
        assert "AI alignment" in queries[1]
        assert "RLHF" in queries[1]

    def test_single_area(self, single_area):
        queries = _build_queries(single_area)
        assert len(queries) == 1
        assert "reinforcement learning" in queries[0]
        assert "PPO" in queries[0]
        assert "DPO" in queries[0]

    def test_empty_areas(self):
        queries = _build_queries([])
        assert queries == []

    def test_areas_with_no_content(self):
        areas = [Area(id="a1", user_id="u1", label="", just_right=[])]
        queries = _build_queries(areas)
        assert queries == []

    def test_terms_capped_at_five(self):
        areas = [
            Area(
                id="a1",
                user_id="u1",
                label="topic",
                just_right=["kw1", "kw2", "kw3", "kw4", "kw5", "kw6"],
            )
        ]
        queries = _build_queries(areas)
        assert len(queries) == 1
        # label + first 4 keywords = 5 terms capped
        parts = queries[0].split()
        assert len(parts) <= 5

    def test_space_separated_terms(self, single_area):
        queries = _build_queries(single_area)
        # S2 uses simple space-separated queries
        assert queries[0] == "reinforcement learning PPO DPO"


# ─── SemanticScholarSource.discover tests ────────────────────────────────────


class TestSemanticScholarDiscover:
    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_returns_normalized_papers(
        self, mock_sleep, s2_source, sample_areas, s2_api_response
    ):
        """discover() should return normalized dicts with all required fields."""
        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = s2_api_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        # Should find the paper (deduplicated across area queries)
        assert len(results) >= 1
        paper = results[0]
        assert paper["id"] == "abc123def456"
        assert paper["source"] == "semantic_scholar"
        assert paper["title"] == "Sparse Autoencoders for Interpretability"
        assert paper["authors"] == ["Alice Researcher", "Bob Scientist"]
        assert paper["abstract"] == "We study SAE features in large language models."
        assert paper["url"] == "https://www.semanticscholar.org/paper/abc123def456"
        assert "2024-06-15" in paper["published"]
        assert paper["fields_of_study"] == ["Computer Science"]
        assert paper["citation_count"] == 42
        assert paper["influential_citation_count"] == 5

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_empty_results(self, mock_sleep, s2_source, sample_areas):
        """discover() returns empty list when S2 returns no data."""
        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"total": 0, "offset": 0, "data": []}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_api_failure_returns_empty(self, mock_sleep, s2_source, sample_areas):
        """discover() handles request exceptions gracefully."""
        with patch.object(s2_source._session, "get") as mock_get:
            mock_get.side_effect = requests.RequestException("Connection refused")

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_filters_papers_before_since(
        self, mock_sleep, s2_source, sample_areas, sample_s2_paper, old_s2_paper
    ):
        """Papers published before `since` should be excluded."""
        api_response = {"total": 2, "offset": 0, "data": [sample_s2_paper, old_s2_paper]}

        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = api_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            since = datetime(2024, 3, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        # Only the recent paper should pass the filter
        titles = [r["title"] for r in results]
        assert "Sparse Autoencoders for Interpretability" in titles
        assert "Ancient Wisdom" not in titles

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_deduplicates_across_queries(
        self, mock_sleep, s2_source, sample_areas, s2_api_response
    ):
        """Papers found in multiple query results are only included once."""
        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = s2_api_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        # Same paper returned by both queries should only appear once
        paper_ids = [r["id"] for r in results]
        assert paper_ids.count("abc123def456") == 1

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_handles_rate_limiting(self, mock_sleep, s2_source, sample_areas, s2_api_response):
        """discover() retries on 429 rate-limit response."""
        with patch.object(s2_source._session, "get") as mock_get:
            rate_limit_resp = MagicMock()
            rate_limit_resp.status_code = 429
            rate_limit_resp.headers = {"Retry-After": "5"}

            success_resp = MagicMock()
            success_resp.status_code = 200
            success_resp.json.return_value = s2_api_response
            success_resp.raise_for_status = MagicMock()

            # First query: rate-limited then succeeds; second query: succeeds
            mock_get.side_effect = [rate_limit_resp, success_resp, success_resp]

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        # Should have retried and gotten results
        assert len(results) >= 1

    def test_discover_no_queries_returns_empty(self, s2_source):
        """When areas produce no queries, discover() returns empty without calling API."""
        areas = [Area(id="a1", user_id="u1", label="", just_right=[])]
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = s2_source.discover(areas, since)
        assert results == []

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_paper_without_date_is_skipped(self, mock_sleep, s2_source, sample_areas):
        """Papers without a publicationDate are excluded."""
        paper_no_date = {
            "paperId": "nodate123",
            "title": "No Date Paper",
            "authors": [],
            "abstract": "Missing date.",
            "url": None,
            "publicationDate": None,
            "fieldsOfStudy": None,
            "citationCount": 0,
            "influentialCitationCount": 0,
        }
        api_response = {"total": 1, "offset": 0, "data": [paper_no_date]}

        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = api_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_naive_since_gets_utc(self, mock_sleep, s2_source, sample_areas, s2_api_response):
        """A timezone-naive since datetime should be handled as UTC."""
        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = s2_api_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1)  # naive
            results = s2_source.discover(sample_areas, since)

        assert len(results) >= 1

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_paper_with_invalid_date_format(self, mock_sleep, s2_source, sample_areas):
        """Papers with unparseable date strings are skipped."""
        bad_date_paper = {
            "paperId": "baddate123",
            "title": "Bad Date Paper",
            "authors": [],
            "abstract": "Has a bad date.",
            "url": None,
            "publicationDate": "not-a-date",
            "fieldsOfStudy": None,
            "citationCount": 0,
            "influentialCitationCount": 0,
        }
        api_response = {"total": 1, "offset": 0, "data": [bad_date_paper]}

        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = api_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_discover_fallback_url_when_url_missing(self, mock_sleep, s2_source, sample_areas):
        """When paper has no url field, a fallback URL is constructed."""
        paper_no_url = {
            "paperId": "xyz789",
            "title": "URL-less Paper",
            "authors": [{"name": "Test"}],
            "abstract": "No url field.",
            "url": None,
            "publicationDate": "2024-06-01",
            "fieldsOfStudy": [],
            "citationCount": 0,
            "influentialCitationCount": 0,
        }
        api_response = {"total": 1, "offset": 0, "data": [paper_no_url]}

        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = api_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = s2_source.discover(sample_areas, since)

        assert len(results) >= 1
        assert results[0]["url"] == "https://www.semanticscholar.org/paper/xyz789"


# ─── SemanticScholarSource.fetch_full_text tests ─────────────────────────────


class TestSemanticScholarFetchFullText:
    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_fetch_full_text_success(self, mock_sleep, s2_source):
        """fetch_full_text downloads open access PDF and extracts text."""
        with patch.object(s2_source._session, "get") as mock_get:
            # First call: get open access PDF URL
            pdf_info_resp = MagicMock()
            pdf_info_resp.status_code = 200
            pdf_info_resp.json.return_value = {
                "openAccessPdf": {"url": "https://example.com/paper.pdf"}
            }
            pdf_info_resp.raise_for_status = MagicMock()

            # Second call: download PDF
            pdf_resp = MagicMock()
            pdf_resp.status_code = 200
            pdf_resp.content = b"%PDF-fake"
            pdf_resp.headers = {"Content-Type": "application/pdf"}
            pdf_resp.raise_for_status = MagicMock()

            mock_get.side_effect = [pdf_info_resp, pdf_resp]

            # Mock fitz
            mock_fitz_mod = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = "Extracted full text content."
            mock_doc = MagicMock()
            mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
            mock_fitz_mod.open.return_value = mock_doc

            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = s2_source.fetch_full_text("abc123def456")

        assert result == "Extracted full text content."
        mock_doc.close.assert_called_once()

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_fetch_full_text_no_open_access_pdf(self, mock_sleep, s2_source):
        """fetch_full_text returns None when no open access PDF exists."""
        with patch.object(s2_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"openAccessPdf": None}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            mock_fitz_mod = MagicMock()
            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = s2_source.fetch_full_text("abc123def456")

        assert result is None

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_fetch_full_text_api_error(self, mock_sleep, s2_source):
        """fetch_full_text returns None when S2 API request fails."""
        with patch.object(s2_source._session, "get") as mock_get:
            mock_get.side_effect = requests.RequestException("Timeout")

            mock_fitz_mod = MagicMock()
            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = s2_source.fetch_full_text("abc123def456")

        assert result is None

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_fetch_full_text_pdf_download_fails(self, mock_sleep, s2_source):
        """fetch_full_text returns None when PDF download fails."""
        with patch.object(s2_source._session, "get") as mock_get:
            # First call succeeds with PDF URL
            pdf_info_resp = MagicMock()
            pdf_info_resp.status_code = 200
            pdf_info_resp.json.return_value = {
                "openAccessPdf": {"url": "https://example.com/paper.pdf"}
            }
            pdf_info_resp.raise_for_status = MagicMock()

            # Second call fails
            mock_get.side_effect = [
                pdf_info_resp,
                requests.RequestException("Download failed"),
            ]

            mock_fitz_mod = MagicMock()
            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = s2_source.fetch_full_text("abc123def456")

        assert result is None

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_fetch_full_text_extraction_fails(self, mock_sleep, s2_source):
        """fetch_full_text returns None when fitz extraction raises."""
        with patch.object(s2_source._session, "get") as mock_get:
            # First call: PDF info
            pdf_info_resp = MagicMock()
            pdf_info_resp.status_code = 200
            pdf_info_resp.json.return_value = {
                "openAccessPdf": {"url": "https://example.com/paper.pdf"}
            }
            pdf_info_resp.raise_for_status = MagicMock()

            # Second call: PDF download success
            pdf_resp = MagicMock()
            pdf_resp.status_code = 200
            pdf_resp.content = b"%PDF-fake"
            pdf_resp.headers = {"Content-Type": "application/pdf"}
            pdf_resp.raise_for_status = MagicMock()

            mock_get.side_effect = [pdf_info_resp, pdf_resp]

            # fitz extraction raises
            mock_fitz_mod = MagicMock()
            mock_fitz_mod.open.side_effect = RuntimeError("Corrupt PDF")

            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = s2_source.fetch_full_text("abc123def456")

        assert result is None

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_fetch_full_text_empty_extraction(self, mock_sleep, s2_source):
        """fetch_full_text returns None when PDF has no extractable text."""
        with patch.object(s2_source._session, "get") as mock_get:
            pdf_info_resp = MagicMock()
            pdf_info_resp.status_code = 200
            pdf_info_resp.json.return_value = {
                "openAccessPdf": {"url": "https://example.com/paper.pdf"}
            }
            pdf_info_resp.raise_for_status = MagicMock()

            pdf_resp = MagicMock()
            pdf_resp.status_code = 200
            pdf_resp.content = b"%PDF-fake"
            pdf_resp.headers = {"Content-Type": "application/pdf"}
            pdf_resp.raise_for_status = MagicMock()

            mock_get.side_effect = [pdf_info_resp, pdf_resp]

            # fitz returns empty pages
            mock_fitz_mod = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = ""
            mock_doc = MagicMock()
            mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
            mock_fitz_mod.open.return_value = mock_doc

            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = s2_source.fetch_full_text("abc123def456")

        assert result is None

    @patch("backend.sources.semantic_scholar.time.sleep")
    def test_fetch_full_text_not_a_pdf_response(self, mock_sleep, s2_source):
        """fetch_full_text returns None when download returns HTML instead of PDF."""
        with patch.object(s2_source._session, "get") as mock_get:
            pdf_info_resp = MagicMock()
            pdf_info_resp.status_code = 200
            pdf_info_resp.json.return_value = {
                "openAccessPdf": {"url": "https://example.com/paper.pdf"}
            }
            pdf_info_resp.raise_for_status = MagicMock()

            html_resp = MagicMock()
            html_resp.status_code = 200
            html_resp.content = b"<html>Not a PDF</html>"
            html_resp.headers = {"Content-Type": "text/html"}
            html_resp.raise_for_status = MagicMock()

            mock_get.side_effect = [pdf_info_resp, html_resp]

            mock_fitz_mod = MagicMock()
            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = s2_source.fetch_full_text("abc123def456")

        assert result is None

    def test_fetch_full_text_no_fitz_installed(self):
        """fetch_full_text returns None if pymupdf is not importable."""
        source = SemanticScholarSource()
        with patch.dict(sys.modules, {"fitz": None}):
            result = source.fetch_full_text("abc123def456")
        assert result is None

    def test_api_key_accepted_by_constructor(self):
        """Constructor with api_key doesn't crash."""
        source = SemanticScholarSource(api_key="test-key-123")
        assert source is not None

    def test_no_api_key_no_header(self):
        """Constructor without api_key does not set x-api-key header."""
        source = SemanticScholarSource()
        assert "x-api-key" not in source._session.headers

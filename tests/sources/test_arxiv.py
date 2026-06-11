"""Comprehensive unit tests for backend.sources.arxiv module."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.shared.models import Area
from backend.sources.arxiv import ArxivSource, _build_query


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_areas() -> list[Area]:
    """Two realistic areas for testing."""
    return [
        Area(
            id="area1",
            user_id="user1",
            label="mechanistic interpretability",
            just_right=["sparse autoencoders", "circuit analysis"],
            frontier="Scaling SAEs to frontier models without losing fidelity",
        ),
        Area(
            id="area2",
            user_id="user1",
            label="AI alignment",
            just_right=["RLHF", "Constitutional AI"],
            frontier="Weak-to-strong generalization techniques",
        ),
    ]


@pytest.fixture
def single_area() -> list[Area]:
    """A single area with minimal fields."""
    return [
        Area(
            id="area1",
            user_id="user1",
            label="reinforcement learning",
            just_right=["PPO"],
        ),
    ]


@pytest.fixture
def arxiv_source() -> ArxivSource:
    return ArxivSource(max_results_per_query=10)


@pytest.fixture
def mock_arxiv_paper():
    """Create a mock arxiv.Result object."""
    paper = MagicMock()
    paper.entry_id = "http://arxiv.org/abs/2401.12345v1"
    paper.title = "Scaling Sparse Autoencoders"
    paper.summary = "We present a method to scale SAEs to frontier models."
    paper.published = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    paper.categories = ["cs.LG", "cs.AI"]
    author1 = MagicMock()
    author1.name = "Alice Smith"
    author2 = MagicMock()
    author2.name = "Bob Jones"
    paper.authors = [author1, author2]
    return paper


@pytest.fixture
def old_arxiv_paper():
    """A paper that precedes the since cutoff."""
    paper = MagicMock()
    paper.entry_id = "http://arxiv.org/abs/2301.00001v1"
    paper.title = "Old Paper"
    paper.summary = "Ancient work."
    paper.published = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    paper.categories = ["cs.LG"]
    author = MagicMock()
    author.name = "Charlie Brown"
    paper.authors = [author]
    return paper


@pytest.fixture
def mock_fitz():
    """Create a mock fitz module and inject it into sys.modules."""
    mock = MagicMock()
    return mock


# ─── _build_query tests ──────────────────────────────────────────────────────


class TestBuildQuery:
    def test_multiple_areas(self, sample_areas):
        query = _build_query(sample_areas)
        # Should contain OR between area clauses
        assert " OR " in query
        # Each area should produce a parenthesized clause
        assert query.count("(") == 2
        assert query.count(")") == 2
        # Area labels should appear
        assert '"mechanistic interpretability"' in query
        assert '"AI alignment"' in query
        # just_right keywords
        assert '"sparse autoencoders"' in query
        assert '"circuit analysis"' in query
        assert "RLHF" in query
        assert '"Constitutional AI"' in query
        # frontier snippet (truncated to 60 chars)
        assert "Scaling SAEs to frontier models" in query

    def test_single_area(self, single_area):
        query = _build_query(single_area)
        # No OR since there's only one area
        assert " OR " not in query
        # Should be a single parenthesized clause
        assert query.startswith("(")
        assert query.endswith(")")
        assert '"reinforcement learning"' in query
        assert "PPO" in query

    def test_empty_areas(self):
        query = _build_query([])
        assert query == ""

    def test_areas_with_no_content(self):
        """Areas with empty label, no keywords, and no frontier produce empty query."""
        areas = [Area(id="a1", user_id="u1", label="", just_right=[], frontier="")]
        query = _build_query(areas)
        assert query == ""

    def test_single_word_not_quoted(self, single_area):
        """Single-word terms should not be quoted."""
        query = _build_query(single_area)
        assert "PPO" in query
        assert '"PPO"' not in query

    def test_multi_word_quoted(self):
        """Multi-word terms (containing spaces) should be quoted."""
        areas = [Area(id="a1", user_id="u1", label="deep learning", just_right=[])]
        query = _build_query(areas)
        assert '"deep learning"' in query

    def test_and_joins_within_area(self, single_area):
        query = _build_query(single_area)
        assert " AND " in query

    def test_terms_capped_at_five(self):
        """Only first 5 terms should be included per area."""
        areas = [
            Area(
                id="a1",
                user_id="u1",
                label="topic",
                just_right=["kw1", "kw2", "kw3", "kw4", "kw5", "kw6"],
                frontier="some frontier text",
            )
        ]
        query = _build_query(areas)
        # label + 4 just_right = 5 terms (capped), so kw5, kw6, and frontier should not appear
        assert "topic" in query
        assert "kw1" in query
        assert "kw4" in query

    def test_frontier_truncated_at_60_chars(self):
        """Frontier snippet is truncated at 60 characters."""
        long_frontier = "A" * 100
        areas = [
            Area(id="a1", user_id="u1", label="topic", just_right=[], frontier=long_frontier)
        ]
        query = _build_query(areas)
        # The frontier part should be at most 60 chars
        assert "A" * 60 in query
        assert "A" * 61 not in query


# ─── ArxivSource.discover tests ──────────────────────────────────────────────


class TestArxivDiscover:
    @patch("backend.sources.arxiv.arxiv.Client")
    @patch("backend.sources.arxiv.arxiv.Search")
    def test_discover_returns_normalized_papers(
        self, mock_search_cls, mock_client_cls, arxiv_source, sample_areas, mock_arxiv_paper
    ):
        """discover() should return a list of dicts with all required fields."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.results.return_value = iter([mock_arxiv_paper])

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert len(results) == 1
        paper = results[0]
        assert paper["id"] == "http://arxiv.org/abs/2401.12345v1"
        assert paper["source"] == "arxiv"
        assert paper["title"] == "Scaling Sparse Autoencoders"
        assert paper["authors"] == ["Alice Smith", "Bob Jones"]
        assert paper["abstract"] == "We present a method to scale SAEs to frontier models."
        assert paper["url"] == "http://arxiv.org/abs/2401.12345v1"
        assert "2024-06-01" in paper["published"]
        assert paper["arxiv_categories"] == ["cs.LG", "cs.AI"]

    @patch("backend.sources.arxiv.arxiv.Client")
    @patch("backend.sources.arxiv.arxiv.Search")
    def test_discover_empty_results(
        self, mock_search_cls, mock_client_cls, arxiv_source, sample_areas
    ):
        """discover() with no matching papers returns empty list."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.results.return_value = iter([])

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.arxiv.arxiv.Client")
    @patch("backend.sources.arxiv.arxiv.Search")
    def test_discover_api_failure_returns_empty(
        self, mock_search_cls, mock_client_cls, arxiv_source, sample_areas
    ):
        """discover() handles exceptions gracefully and returns empty list."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.results.side_effect = RuntimeError("Network error")

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.arxiv.arxiv.Client")
    @patch("backend.sources.arxiv.arxiv.Search")
    def test_discover_filters_papers_before_since(
        self, mock_search_cls, mock_client_cls, arxiv_source, sample_areas, mock_arxiv_paper, old_arxiv_paper
    ):
        """Papers published before `since` should be excluded."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # Return papers in descending order: new first, then old
        mock_client.results.return_value = iter([mock_arxiv_paper, old_arxiv_paper])

        since = datetime(2024, 3, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        # Only the recent paper should be included
        assert len(results) == 1
        assert results[0]["title"] == "Scaling Sparse Autoencoders"

    @patch("backend.sources.arxiv.arxiv.Client")
    @patch("backend.sources.arxiv.arxiv.Search")
    def test_discover_stops_at_old_paper(
        self, mock_search_cls, mock_client_cls, arxiv_source, sample_areas, old_arxiv_paper
    ):
        """Since results are sorted newest-first, hitting an old paper breaks the loop."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.results.return_value = iter([old_arxiv_paper])

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert results == []

    def test_discover_empty_query_returns_empty(self, arxiv_source):
        """When areas produce no query, discover() returns empty without calling API."""
        empty_areas = [Area(id="a1", user_id="u1", label="", just_right=[])]
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(empty_areas, since)
        assert results == []

    @patch("backend.sources.arxiv.arxiv.Client")
    @patch("backend.sources.arxiv.arxiv.Search")
    def test_discover_naive_since_gets_utc(
        self, mock_search_cls, mock_client_cls, arxiv_source, sample_areas
    ):
        """A timezone-naive `since` should be treated as UTC."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.results.return_value = iter([])

        # Naive datetime (no tzinfo)
        since = datetime(2024, 1, 1)
        results = arxiv_source.discover(sample_areas, since)
        # Should not crash
        assert results == []

    @patch("backend.sources.arxiv.arxiv.Client")
    @patch("backend.sources.arxiv.arxiv.Search")
    def test_discover_paper_with_naive_published_date(
        self, mock_search_cls, mock_client_cls, arxiv_source, sample_areas
    ):
        """A paper with naive published datetime should still be processed."""
        paper = MagicMock()
        paper.entry_id = "http://arxiv.org/abs/2401.99999v1"
        paper.title = "Naive Date Paper"
        paper.summary = "Test."
        paper.published = datetime(2024, 6, 15, 10, 0, 0)  # naive
        paper.categories = ["cs.CL"]
        author = MagicMock()
        author.name = "Test Author"
        paper.authors = [author]

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.results.return_value = iter([paper])

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert len(results) == 1
        assert results[0]["title"] == "Naive Date Paper"


# ─── ArxivSource.fetch_full_text tests ───────────────────────────────────────


class TestArxivFetchFullText:
    @patch("backend.shared.pdf.extract_text_from_pdf")
    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_fetch_full_text_success(self, mock_get, mock_sleep, mock_extract, arxiv_source):
        """fetch_full_text downloads PDF and extracts text correctly."""
        # Mock PDF download
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-fake-content"
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # Mock PDF text extraction
        mock_extract.return_value = "Page 1 text content here."

        result = arxiv_source.fetch_full_text("2401.12345")

        assert result == "Page 1 text content here."
        mock_get.assert_called_once_with("https://arxiv.org/pdf/2401.12345.pdf", timeout=60)
        mock_extract.assert_called_once_with(b"%PDF-fake-content")

    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_fetch_full_text_pdf_unavailable(self, mock_get, mock_sleep, arxiv_source):
        """fetch_full_text returns None when PDF download fails."""
        import requests

        mock_get.side_effect = requests.RequestException("404 Not Found")

        mock_fitz_mod = MagicMock()
        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = arxiv_source.fetch_full_text("2401.99999")
        assert result is None

    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_fetch_full_text_extraction_fails(self, mock_get, mock_sleep, arxiv_source):
        """fetch_full_text returns None when text extraction raises an exception."""
        # Mock successful PDF download
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-fake"
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # Mock fitz raising an error
        mock_fitz_mod = MagicMock()
        mock_fitz_mod.open.side_effect = RuntimeError("Corrupt PDF")

        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = arxiv_source.fetch_full_text("2401.12345")
        assert result is None

    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_fetch_full_text_empty_extraction(self, mock_get, mock_sleep, arxiv_source):
        """fetch_full_text returns None when PDF produces empty text."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-fake"
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # Mock fitz returning pages with empty text
        mock_fitz_mod = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = ""
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_fitz_mod.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = arxiv_source.fetch_full_text("2401.12345")
        assert result is None

    @patch("backend.shared.pdf.extract_text_from_pdf")
    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_fetch_full_text_multi_page(self, mock_get, mock_sleep, mock_extract, arxiv_source):
        """fetch_full_text joins text from multiple pages with double newline."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-fake"
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        mock_extract.return_value = "Page 1 content\n\nPage 2 content"

        result = arxiv_source.fetch_full_text("2401.12345")
        assert result == "Page 1 content\n\nPage 2 content"

    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_fetch_full_text_not_a_pdf_response(self, mock_get, mock_sleep, arxiv_source):
        """fetch_full_text returns None when response is HTML instead of PDF."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html>Error</html>"
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        mock_fitz_mod = MagicMock()
        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = arxiv_source.fetch_full_text("2401.12345")
        assert result is None

    def test_fetch_full_text_url_from_abs_url(self, arxiv_source):
        """_resolve_pdf_url converts abs URL to pdf URL."""
        url = arxiv_source._resolve_pdf_url("http://arxiv.org/abs/2401.12345v1")
        assert url == "http://arxiv.org/pdf/2401.12345v1.pdf"

    def test_fetch_full_text_url_from_bare_id(self, arxiv_source):
        """_resolve_pdf_url builds full URL from bare paper ID."""
        url = arxiv_source._resolve_pdf_url("2401.12345")
        assert url == "https://arxiv.org/pdf/2401.12345.pdf"

    def test_fetch_full_text_url_already_pdf(self, arxiv_source):
        """_resolve_pdf_url handles URLs that already end in .pdf."""
        url = arxiv_source._resolve_pdf_url("http://arxiv.org/pdf/2401.12345v1.pdf")
        assert url == "http://arxiv.org/pdf/2401.12345v1.pdf"

    def test_fetch_full_text_no_fitz_installed(self):
        """fetch_full_text returns None if pymupdf is not importable."""
        source = ArxivSource()
        # Remove fitz from sys.modules if present, then make import fail
        with patch.dict(sys.modules, {"fitz": None}):
            result = source.fetch_full_text("2401.12345")
        assert result is None

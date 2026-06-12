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
def mock_fitz():
    """Create a mock fitz module and inject it into sys.modules."""
    mock = MagicMock()
    return mock


_SAMPLE_ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <published>2026-06-01T00:00:00Z</published>
    <title>Test Paper Title</title>
    <summary>Test abstract content</summary>
    <author><name>Alice Researcher</name></author>
    <author><name>Bob Scientist</name></author>
    <arxiv:primary_category term="cs.AI"/>
    <category term="cs.AI"/>
    <category term="cs.CL"/>
  </entry>
</feed>
"""

_EMPTY_ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
</feed>
"""

_OLD_PAPER_ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <published>2023-01-01T00:00:00Z</published>
    <title>Old Paper</title>
    <summary>Ancient work</summary>
    <author><name>Charlie Brown</name></author>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
  </entry>
</feed>
"""


# ─── _build_query tests ──────────────────────────────────────────────────────


class TestBuildQuery:
    def test_build_query_with_queries_provided(self, sample_areas, arxiv_source):
        """When discover() is called with explicit queries, the arXiv query uses them."""
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)

        with patch("backend.sources.arxiv.requests.get") as mock_get, \
             patch("backend.sources.arxiv.time.sleep"):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = _EMPTY_ATOM_XML
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            arxiv_source.discover(sample_areas, since, queries=["q1", "q2"])

            # Verify the search_query param passed to requests.get
            call_kwargs = mock_get.call_args
            params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
            assert params["search_query"] == "all:q1 OR all:q2"

    @patch("backend.shared.query_gen.generate_all_queries")
    def test_build_query_llm_fallback(self, mock_gen, sample_areas):
        """When no queries are provided, _build_query uses generate_all_queries."""
        mock_gen.return_value = ["fallback1"]

        query = _build_query(sample_areas)

        mock_gen.assert_called_once_with(sample_areas)
        assert 'all:"fallback1"' in query


# ─── ArxivSource.discover tests ──────────────────────────────────────────────


class TestArxivDiscover:
    @patch("backend.shared.query_gen.generate_all_queries")
    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_discover_returns_normalized_papers(
        self, mock_get, mock_sleep, mock_gen, arxiv_source, sample_areas
    ):
        """discover() should return a list of dicts with all required fields."""
        mock_gen.return_value = ["test query"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _SAMPLE_ATOM_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert len(results) == 1
        paper = results[0]
        assert paper["id"] == "http://arxiv.org/abs/2401.12345v1"
        assert paper["source"] == "arxiv"
        assert paper["title"] == "Test Paper Title"
        assert paper["authors"] == ["Alice Researcher", "Bob Scientist"]
        assert paper["abstract"] == "Test abstract content"
        assert paper["url"] == "http://arxiv.org/abs/2401.12345v1"
        assert "2026-06-01" in paper["published"]
        assert "cs.AI" in paper["arxiv_categories"]
        assert "cs.CL" in paper["arxiv_categories"]

    @patch("backend.shared.query_gen.generate_all_queries")
    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_discover_empty_results(
        self, mock_get, mock_sleep, mock_gen, arxiv_source, sample_areas
    ):
        """discover() with no matching papers returns empty list."""
        mock_gen.return_value = ["test query"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _EMPTY_ATOM_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.shared.query_gen.generate_all_queries")
    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests")
    def test_discover_api_failure_returns_empty(
        self, mock_requests, mock_sleep, mock_gen, arxiv_source, sample_areas
    ):
        """discover() handles request exceptions gracefully and returns empty list."""
        mock_gen.return_value = ["test query"]
        # Create a real-ish exception class on the mock requests module
        mock_requests.RequestException = type("RequestException", (Exception,), {})
        mock_requests.get.side_effect = mock_requests.RequestException("Network error")

        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.shared.query_gen.generate_all_queries")
    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_discover_filters_papers_before_since(
        self, mock_get, mock_sleep, mock_gen, arxiv_source, sample_areas
    ):
        """Papers published before `since` should be excluded (break on old paper)."""
        mock_gen.return_value = ["test query"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _OLD_PAPER_ATOM_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 3, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.shared.query_gen.generate_all_queries")
    def test_discover_empty_query_returns_empty(self, mock_gen, arxiv_source):
        """When areas produce no query, discover() returns empty without calling API."""
        mock_gen.return_value = []
        empty_areas = [Area(id="a1", user_id="u1", label="", just_right=[])]
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(empty_areas, since)
        assert results == []

    @patch("backend.shared.query_gen.generate_all_queries")
    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_discover_naive_since_gets_utc(
        self, mock_get, mock_sleep, mock_gen, arxiv_source, sample_areas
    ):
        """A timezone-naive `since` should be treated as UTC."""
        mock_gen.return_value = ["test query"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _EMPTY_ATOM_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # Naive datetime (no tzinfo)
        since = datetime(2026, 1, 1)
        results = arxiv_source.discover(sample_areas, since)
        # Should not crash
        assert results == []

    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_discover_with_explicit_queries(
        self, mock_get, mock_sleep, arxiv_source, sample_areas
    ):
        """discover() with explicit queries parameter uses them directly."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _SAMPLE_ATOM_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since, queries=["sparse autoencoders"])

        assert len(results) == 1
        # Verify that generate_all_queries was NOT called (no mock needed since we provide queries)
        params = mock_get.call_args[1]["params"]
        assert params["search_query"] == "all:sparse autoencoders"

    @patch("backend.shared.query_gen.generate_all_queries")
    @patch("backend.sources.arxiv.time.sleep")
    @patch("backend.sources.arxiv.requests.get")
    def test_discover_date_filtering(
        self, mock_get, mock_sleep, mock_gen, arxiv_source, sample_areas
    ):
        """Papers older than `since` are filtered out by date comparison."""
        mock_gen.return_value = ["query"]

        # XML with a paper from 2026-06-01 and another from 2023-01-01
        xml_with_both = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <published>2026-06-01T00:00:00Z</published>
    <title>New Paper</title>
    <summary>Recent work</summary>
    <author><name>Alice</name></author>
    <arxiv:primary_category term="cs.AI"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <published>2023-01-01T00:00:00Z</published>
    <title>Old Paper</title>
    <summary>Ancient work</summary>
    <author><name>Bob</name></author>
    <arxiv:primary_category term="cs.LG"/>
  </entry>
</feed>
"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = xml_with_both
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        results = arxiv_source.discover(sample_areas, since)

        # Only the new paper should be present; old paper triggers break
        assert len(results) == 1
        assert results[0]["title"] == "New Paper"


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

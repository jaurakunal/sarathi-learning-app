"""Comprehensive unit tests for backend.sources.hf_daily_papers module."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.shared.models import Area
from backend.sources.hf_daily_papers import (
    HFDailyPapersSource,
    _extract_keywords,
    _paper_matches_keywords,
)


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
def hf_source() -> HFDailyPapersSource:
    return HFDailyPapersSource(max_papers=50)


@pytest.fixture
def sample_hf_paper_entry() -> dict:
    """A typical HF Daily Papers API response entry."""
    return {
        "title": "Sparse Autoencoders Reveal Hidden Features",
        "publishedAt": "2024-06-15T12:00:00Z",
        "numUpvotes": 25,
        "paper": {
            "id": "2406.12345",
            "title": "Sparse Autoencoders Reveal Hidden Features",
            "summary": "We train sparse autoencoders on language model activations.",
            "authors": [
                {"name": "Alice Researcher"},
                {"name": "Bob Scientist"},
            ],
            "publishedAt": "2024-06-15T12:00:00Z",
            "upvotes": 30,
        },
    }


@pytest.fixture
def old_hf_paper_entry() -> dict:
    """An HF paper published before the since cutoff."""
    return {
        "title": "Old Interpretability Paper",
        "publishedAt": "2022-01-01T00:00:00Z",
        "paper": {
            "id": "2201.00001",
            "title": "Old Interpretability Paper",
            "summary": "Early work on interpretability with sparse autoencoders.",
            "authors": [{"name": "Charlie Oldtimer"}],
            "publishedAt": "2022-01-01T00:00:00Z",
            "upvotes": 5,
        },
    }


@pytest.fixture
def irrelevant_hf_paper_entry() -> dict:
    """A paper that does not match any keywords."""
    return {
        "title": "Protein Folding via Deep Learning",
        "publishedAt": "2024-06-10T00:00:00Z",
        "paper": {
            "id": "2406.99999",
            "title": "Protein Folding via Deep Learning",
            "summary": "We solve protein structure prediction problems.",
            "authors": [{"name": "Dr. Biology"}],
            "publishedAt": "2024-06-10T00:00:00Z",
            "upvotes": 100,
        },
    }


# ─── Helper function tests ───────────────────────────────────────────────────


class TestExtractKeywords:
    def test_extracts_labels_and_just_right(self, sample_areas):
        keywords = _extract_keywords(sample_areas)
        assert "mechanistic interpretability" in keywords
        assert "sparse autoencoders" in keywords
        assert "circuit analysis" in keywords
        assert "ai alignment" in keywords
        assert "rlhf" in keywords

    def test_all_lowercased(self, sample_areas):
        keywords = _extract_keywords(sample_areas)
        for kw in keywords:
            assert kw == kw.lower()

    def test_empty_areas(self):
        keywords = _extract_keywords([])
        assert keywords == []

    def test_area_with_no_content(self):
        areas = [Area(id="a1", user_id="u1", label="", just_right=[])]
        keywords = _extract_keywords(areas)
        assert keywords == []

    def test_does_not_include_frontier(self, sample_areas):
        """Frontier text is NOT included in keywords (only label + just_right)."""
        keywords = _extract_keywords(sample_areas)
        assert "scaling saes" not in keywords


class TestPaperMatchesKeywords:
    def test_matches_in_title(self):
        assert _paper_matches_keywords(
            "Sparse Autoencoders for LLMs", "", ["sparse autoencoders"]
        )

    def test_matches_in_abstract(self):
        assert _paper_matches_keywords(
            "Some Title", "We study sparse autoencoders.", ["sparse autoencoders"]
        )

    def test_no_match(self):
        assert not _paper_matches_keywords(
            "Protein Folding", "Biology paper.", ["sparse autoencoders", "rlhf"]
        )

    def test_empty_keywords_matches_all(self):
        """When no keywords are provided, all papers match."""
        assert _paper_matches_keywords("Anything", "Goes", [])

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        assert _paper_matches_keywords(
            "SPARSE AUTOENCODERS", "", ["sparse autoencoders"]
        )


# ─── HFDailyPapersSource.discover tests ─────────────────────────────────────


class TestHFDailyPapersDiscover:
    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_returns_normalized_papers(
        self, mock_get, mock_sleep, hf_source, sample_areas, sample_hf_paper_entry
    ):
        """discover() returns properly normalized dicts."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [sample_hf_paper_entry]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert len(results) == 1
        paper = results[0]
        assert paper["id"] == "2406.12345"
        assert paper["source"] == "hf_daily_papers"
        assert paper["title"] == "Sparse Autoencoders Reveal Hidden Features"
        assert paper["authors"] == ["Alice Researcher", "Bob Scientist"]
        assert paper["abstract"] == "We train sparse autoencoders on language model activations."
        assert paper["url"] == "https://huggingface.co/papers/2406.12345"
        assert "2024-06-15" in paper["published"]
        assert paper["upvotes"] == 30

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_empty_results(self, mock_get, mock_sleep, hf_source, sample_areas):
        """discover() returns empty list when API returns no papers."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_api_failure_returns_empty(self, mock_get, mock_sleep, hf_source, sample_areas):
        """discover() handles API failures gracefully."""
        mock_get.side_effect = requests.RequestException("Network error")

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_filters_papers_before_since(
        self, mock_get, mock_sleep, hf_source, sample_areas, sample_hf_paper_entry, old_hf_paper_entry
    ):
        """Papers published before `since` are excluded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [sample_hf_paper_entry, old_hf_paper_entry]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 3, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert len(results) == 1
        assert results[0]["id"] == "2406.12345"

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_filters_irrelevant_papers(
        self, mock_get, mock_sleep, hf_source, sample_areas, sample_hf_paper_entry, irrelevant_hf_paper_entry
    ):
        """Papers not matching keywords are excluded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [sample_hf_paper_entry, irrelevant_hf_paper_entry]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert len(results) == 1
        assert results[0]["title"] == "Sparse Autoencoders Reveal Hidden Features"

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_respects_max_papers(self, mock_get, mock_sleep, sample_areas):
        """discover() stops collecting once max_papers is reached."""
        source = HFDailyPapersSource(max_papers=1)

        entries = [
            {
                "title": f"SAE Paper {i}",
                "publishedAt": f"2024-06-{10+i:02d}T00:00:00Z",
                "paper": {
                    "id": f"2406.{10000+i}",
                    "title": f"SAE Paper {i}",
                    "summary": "Sparse autoencoders are great.",
                    "authors": [{"name": f"Author {i}"}],
                    "publishedAt": f"2024-06-{10+i:02d}T00:00:00Z",
                    "upvotes": i * 10,
                },
            }
            for i in range(5)
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = entries
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = source.discover(sample_areas, since)

        assert len(results) == 1

    def test_discover_no_areas_returns_empty(self, hf_source):
        """discover() with empty areas list returns empty."""
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover([], since)
        assert results == []

    def test_discover_areas_with_no_keywords_returns_empty(self, hf_source):
        """discover() when areas produce no keywords returns empty."""
        areas = [Area(id="a1", user_id="u1", label="", just_right=[])]
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(areas, since)
        assert results == []

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_naive_since_gets_utc(
        self, mock_get, mock_sleep, hf_source, sample_areas, sample_hf_paper_entry
    ):
        """A timezone-naive since is treated as UTC."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [sample_hf_paper_entry]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1)  # naive
        results = hf_source.discover(sample_areas, since)

        assert len(results) == 1

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_paper_with_no_published_date_skipped(
        self, mock_get, mock_sleep, hf_source, sample_areas
    ):
        """Papers with missing publishedAt are skipped."""
        entry_no_date = {
            "title": "No Date",
            "publishedAt": "",
            "paper": {
                "id": "2406.nodate",
                "title": "No Date Paper on autoencoders",
                "summary": "sparse autoencoders something.",
                "authors": [],
                "publishedAt": "",
                "upvotes": 0,
            },
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [entry_no_date]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_authors_as_strings(self, mock_get, mock_sleep, hf_source, sample_areas):
        """discover() handles authors stored as plain strings."""
        entry = {
            "title": "Sparse autoencoders paper",
            "publishedAt": "2024-06-15T00:00:00Z",
            "paper": {
                "id": "2406.strauth",
                "title": "Sparse autoencoders paper",
                "summary": "Testing autoencoders.",
                "authors": ["Alice", "Bob"],  # strings instead of dicts
                "publishedAt": "2024-06-15T00:00:00Z",
                "upvotes": 10,
            },
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [entry]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert len(results) == 1
        assert results[0]["authors"] == ["Alice", "Bob"]

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_handles_dict_api_response(self, mock_get, mock_sleep, hf_source, sample_areas, sample_hf_paper_entry):
        """discover() handles API returning a dict with 'papers' key."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"papers": [sample_hf_paper_entry]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert len(results) == 1

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_discover_handles_json_parse_error(self, mock_get, mock_sleep, hf_source, sample_areas):
        """discover() handles JSON parse errors gracefully."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = hf_source.discover(sample_areas, since)

        assert results == []


# ─── HFDailyPapersSource.fetch_full_text tests ──────────────────────────────


class TestHFDailyPapersFetchFullText:
    @patch("backend.shared.pdf.extract_text_from_pdf")
    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_fetch_full_text_success(self, mock_get, mock_sleep, mock_extract, hf_source):
        """fetch_full_text downloads from arXiv and extracts text."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-1.5 fake pdf"
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        mock_extract.return_value = "Full text of HF paper."

        result = hf_source.fetch_full_text("2406.12345")

        assert result == "Full text of HF paper."
        mock_get.assert_called_once_with("https://arxiv.org/pdf/2406.12345.pdf", timeout=60)
        mock_extract.assert_called_once_with(b"%PDF-1.5 fake pdf")

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_fetch_full_text_pdf_unavailable(self, mock_get, mock_sleep, hf_source):
        """fetch_full_text returns None when PDF download fails."""
        mock_get.side_effect = requests.RequestException("Not found")

        mock_fitz_mod = MagicMock()
        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = hf_source.fetch_full_text("2406.12345")
        assert result is None

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_fetch_full_text_extraction_fails(self, mock_get, mock_sleep, hf_source):
        """fetch_full_text returns None when text extraction raises."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-fake"
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        mock_fitz_mod = MagicMock()
        mock_fitz_mod.open.side_effect = RuntimeError("Corrupt PDF")

        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = hf_source.fetch_full_text("2406.12345")
        assert result is None

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_fetch_full_text_empty_extraction(self, mock_get, mock_sleep, hf_source):
        """fetch_full_text returns None when PDF has no text."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-fake"
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        mock_fitz_mod = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "   "  # whitespace only
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_fitz_mod.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = hf_source.fetch_full_text("2406.12345")
        assert result is None

    def test_fetch_full_text_empty_paper_id(self, hf_source):
        """fetch_full_text returns None for empty paper_id."""
        mock_fitz_mod = MagicMock()
        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = hf_source.fetch_full_text("")
        assert result is None

    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_fetch_full_text_html_response(self, mock_get, mock_sleep, hf_source):
        """fetch_full_text returns None when response is HTML."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html>Error page</html>"
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        mock_fitz_mod = MagicMock()
        with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
            result = hf_source.fetch_full_text("2406.12345")
        assert result is None

    def test_fetch_full_text_no_fitz_installed(self):
        """fetch_full_text returns None if pymupdf is not importable."""
        source = HFDailyPapersSource()
        with patch.dict(sys.modules, {"fitz": None}):
            result = source.fetch_full_text("2406.12345")
        assert result is None

    @patch("backend.shared.pdf.extract_text_from_pdf")
    @patch("backend.sources.hf_daily_papers.time.sleep")
    @patch("backend.sources.hf_daily_papers.requests.get")
    def test_fetch_full_text_multi_page(self, mock_get, mock_sleep, mock_extract, hf_source):
        """fetch_full_text joins multi-page text correctly."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"%PDF-fake"
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        mock_extract.return_value = "Introduction\n\nMethods\n\nResults"

        result = hf_source.fetch_full_text("2406.12345")
        assert result == "Introduction\n\nMethods\n\nResults"

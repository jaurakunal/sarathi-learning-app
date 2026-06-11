"""Comprehensive unit tests for backend.sources.openreview module."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.shared.models import Area
from backend.sources.openreview import (
    OpenReviewSource,
    _build_search_terms,
    _epoch_ms,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_areas() -> list[Area]:
    return [
        Area(
            id="area1",
            user_id="user1",
            label="mechanistic interpretability",
            just_right=["sparse autoencoders", "circuit analysis", "superposition"],
            frontier="",
        ),
        Area(
            id="area2",
            user_id="user1",
            label="AI alignment",
            just_right=["RLHF", "Constitutional AI"],
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
def openreview_source() -> OpenReviewSource:
    return OpenReviewSource(max_results_per_query=10)


@pytest.fixture
def sample_openreview_note() -> dict:
    """A typical OpenReview API v2 note object."""
    # cdate = 2024-06-15 00:00:00 UTC in milliseconds
    cdate_ms = int(datetime(2024, 6, 15, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    return {
        "id": "note123ABC",
        "cdate": cdate_ms,
        "content": {
            "title": {"value": "Sparse Autoencoders at Scale"},
            "authors": {"value": ["Alice Researcher", "Bob Scientist"]},
            "abstract": {"value": "We scale sparse autoencoders to frontier LLMs."},
            "venue": {"value": "ICLR 2025"},
        },
    }


@pytest.fixture
def old_openreview_note() -> dict:
    """An OpenReview note created before the since cutoff."""
    # cdate = 2022-01-01 00:00:00 UTC in milliseconds
    cdate_ms = int(datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    return {
        "id": "oldNote999",
        "cdate": cdate_ms,
        "content": {
            "title": {"value": "Ancient Research"},
            "authors": {"value": ["Old Timer"]},
            "abstract": {"value": "Very old paper."},
            "venue": {"value": "NeurIPS 2021"},
        },
    }


@pytest.fixture
def note_with_rating() -> dict:
    """A note that has a rating field in content."""
    cdate_ms = int(datetime(2024, 6, 10, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    return {
        "id": "ratedNote1",
        "cdate": cdate_ms,
        "content": {
            "title": {"value": "Rated Paper"},
            "authors": {"value": ["Reviewer Friendly"]},
            "abstract": {"value": "This paper has a rating."},
            "venue": {"value": "ICML 2024"},
            "rating": {"value": "8: Strong Accept"},
        },
    }


# ─── Helper function tests ───────────────────────────────────────────────────


class TestBuildSearchTerms:
    def test_multiple_areas(self, sample_areas):
        terms = _build_search_terms(sample_areas)
        assert len(terms) == 2
        # First area: label + up to 4 just_right keywords
        assert "mechanistic interpretability" in terms[0]
        assert "sparse autoencoders" in terms[0]
        assert "circuit analysis" in terms[0]
        assert "superposition" in terms[0]
        # Second area
        assert "AI alignment" in terms[1]
        assert "RLHF" in terms[1]
        assert "Constitutional AI" in terms[1]

    def test_single_area(self, single_area):
        terms = _build_search_terms(single_area)
        assert len(terms) == 1
        assert "reinforcement learning" in terms[0]
        assert "PPO" in terms[0]
        assert "DPO" in terms[0]

    def test_empty_areas(self):
        terms = _build_search_terms([])
        assert terms == []

    def test_areas_with_no_content(self):
        areas = [Area(id="a1", user_id="u1", label="", just_right=[])]
        terms = _build_search_terms(areas)
        assert terms == []

    def test_just_right_capped_at_four(self):
        """just_right keywords capped at 4 per area."""
        areas = [
            Area(
                id="a1",
                user_id="u1",
                label="topic",
                just_right=["kw1", "kw2", "kw3", "kw4", "kw5", "kw6"],
            )
        ]
        terms = _build_search_terms(areas)
        parts = terms[0].split()
        # label(1) + first 4 keywords = 5 parts max
        assert len(parts) == 5
        assert "kw5" not in terms[0]
        assert "kw6" not in terms[0]


class TestEpochMs:
    def test_aware_datetime(self):
        dt = datetime(2024, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
        result = _epoch_ms(dt)
        assert result == int(dt.timestamp() * 1000)

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2024, 6, 15, 0, 0, 0)
        result = _epoch_ms(dt)
        expected = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        assert result == expected

    def test_epoch_zero(self):
        dt = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert _epoch_ms(dt) == 0


# ─── OpenReviewSource.discover tests ─────────────────────────────────────────


class TestOpenReviewDiscover:
    @patch("backend.sources.openreview.time.sleep")
    def test_discover_returns_normalized_papers(
        self, mock_sleep, openreview_source, sample_areas, sample_openreview_note
    ):
        """discover() returns properly normalized dicts with all required fields."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": [sample_openreview_note]}
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert len(results) >= 1
        paper = results[0]
        assert paper["id"] == "note123ABC"
        assert paper["source"] == "openreview"
        assert paper["title"] == "Sparse Autoencoders at Scale"
        assert paper["authors"] == ["Alice Researcher", "Bob Scientist"]
        assert paper["abstract"] == "We scale sparse autoencoders to frontier LLMs."
        assert paper["url"] == "https://openreview.net/forum?id=note123ABC"
        assert "2024-06-15" in paper["published"]
        assert paper["venue"] == "ICLR 2025"
        assert "peer_review_score" in paper

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_empty_results(self, mock_sleep, openreview_source, sample_areas):
        """discover() returns empty list when no notes are found."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": []}
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_api_failure_returns_empty(self, mock_sleep, openreview_source, sample_areas):
        """discover() handles request exceptions gracefully."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_get.side_effect = requests.RequestException("Connection refused")

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_filters_papers_before_since(
        self, mock_sleep, openreview_source, sample_areas, sample_openreview_note, old_openreview_note
    ):
        """Papers created before `since` are excluded."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": [sample_openreview_note, old_openreview_note]}
            mock_get.return_value = mock_resp

            since = datetime(2024, 3, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        titles = [r["title"] for r in results]
        assert "Sparse Autoencoders at Scale" in titles
        assert "Ancient Research" not in titles

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_deduplicates_across_strategies(
        self, mock_sleep, openreview_source, sample_areas, sample_openreview_note
    ):
        """The same paper found by both search and venue is included only once."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": [sample_openreview_note]}
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        paper_ids = [r["id"] for r in results]
        assert paper_ids.count("note123ABC") == 1

    def test_discover_no_search_terms_returns_empty(self, openreview_source):
        """discover() with areas that produce no search terms returns empty."""
        areas = [Area(id="a1", user_id="u1", label="", just_right=[])]
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = openreview_source.discover(areas, since)
        assert results == []

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_naive_since_gets_utc(
        self, mock_sleep, openreview_source, sample_areas, sample_openreview_note
    ):
        """A timezone-naive since is treated as UTC."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": [sample_openreview_note]}
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1)  # naive
            results = openreview_source.discover(sample_areas, since)

        assert len(results) >= 1

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_handles_rate_limiting(
        self, mock_sleep, openreview_source, sample_areas, sample_openreview_note
    ):
        """discover() handles 429 rate limit responses."""
        with patch.object(openreview_source._session, "get") as mock_get:
            rate_resp = MagicMock()
            rate_resp.status_code = 429
            rate_resp.headers = {"Retry-After": "5"}

            success_resp = MagicMock()
            success_resp.status_code = 200
            success_resp.json.return_value = {"notes": [sample_openreview_note]}

            # First call rate limited, second succeeds, rest succeed
            mock_get.side_effect = [rate_resp, success_resp] + [success_resp] * 50

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert len(results) >= 1

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_non_200_returns_empty_for_term(
        self, mock_sleep, openreview_source, sample_areas
    ):
        """Non-200, non-429 responses result in empty results for that term."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = "Internal Server Error"
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_note_without_title_is_skipped(
        self, mock_sleep, openreview_source, sample_areas
    ):
        """Notes with missing titles are skipped."""
        cdate_ms = int(datetime(2024, 6, 15, tzinfo=timezone.utc).timestamp() * 1000)
        note_no_title = {
            "id": "noTitle1",
            "cdate": cdate_ms,
            "content": {
                "title": {"value": ""},
                "authors": {"value": ["Author"]},
                "abstract": {"value": "Abstract"},
                "venue": {"value": ""},
            },
        }

        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": [note_no_title]}
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_note_without_id_is_skipped(
        self, mock_sleep, openreview_source, sample_areas
    ):
        """Notes with missing id are skipped."""
        cdate_ms = int(datetime(2024, 6, 15, tzinfo=timezone.utc).timestamp() * 1000)
        note_no_id = {
            "id": "",
            "cdate": cdate_ms,
            "content": {
                "title": {"value": "Some Paper"},
                "authors": {"value": ["Author"]},
                "abstract": {"value": "Abstract"},
                "venue": {"value": ""},
            },
        }

        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": [note_no_id]}
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert results == []

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_title_as_plain_string(
        self, mock_sleep, openreview_source, sample_areas
    ):
        """Notes with title as a plain string (not dict) are handled."""
        cdate_ms = int(datetime(2024, 6, 15, tzinfo=timezone.utc).timestamp() * 1000)
        note_str_title = {
            "id": "strTitle1",
            "cdate": cdate_ms,
            "content": {
                "title": "Direct Title String",
                "authors": ["Author A"],
                "abstract": "Some abstract.",
                "venue": "ICLR 2025",
            },
        }

        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": [note_str_title]}
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert len(results) >= 1
        assert results[0]["title"] == "Direct Title String"
        assert results[0]["authors"] == ["Author A"]
        assert results[0]["venue"] == "ICLR 2025"

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_with_embedded_rating(
        self, mock_sleep, openreview_source, sample_areas, note_with_rating
    ):
        """Papers with embedded rating get a peer_review_score."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": [note_with_rating]}
            mock_get.return_value = mock_resp

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        # The rating "8: Strong Accept" should be parsed to 8.0
        assert len(results) >= 1
        assert results[0]["peer_review_score"] == 8.0

    @patch("backend.sources.openreview.time.sleep")
    def test_discover_fetches_review_scores_when_no_embedded_rating(
        self, mock_sleep, openreview_source, sample_areas, sample_openreview_note
    ):
        """When no embedded rating, _fetch_average_review_score is called."""
        with patch.object(openreview_source._session, "get") as mock_get:
            # Search response
            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {"notes": [sample_openreview_note]}

            # Review fetch response
            review_resp = MagicMock()
            review_resp.status_code = 200
            review_resp.json.return_value = {
                "notes": [
                    {"content": {"rating": {"value": "7: Accept"}}},
                    {"content": {"rating": {"value": "6: Weak Accept"}}},
                ]
            }

            mock_get.side_effect = [search_resp, review_resp] * 20

            since = datetime(2024, 1, 1, tzinfo=timezone.utc)
            results = openreview_source.discover(sample_areas, since)

        assert len(results) >= 1
        # Average of 7 and 6 = 6.5
        assert results[0]["peer_review_score"] == 6.5


# ─── OpenReviewSource.fetch_full_text tests ──────────────────────────────────


class TestOpenReviewFetchFullText:
    @patch("backend.shared.pdf.extract_text_from_pdf")
    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_full_text_success(self, mock_sleep, mock_extract, openreview_source):
        """fetch_full_text downloads from OpenReview and extracts text."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"%PDF-1.5 fake content"
            mock_resp.headers = {"Content-Type": "application/pdf"}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            mock_extract.return_value = "OpenReview paper full text."

            result = openreview_source.fetch_full_text("note123ABC")

        assert result == "OpenReview paper full text."
        mock_get.assert_called_once_with("https://openreview.net/pdf?id=note123ABC", timeout=60)
        mock_extract.assert_called_once_with(b"%PDF-1.5 fake content")

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_full_text_pdf_not_found(self, mock_sleep, openreview_source):
        """fetch_full_text returns None when PDF returns 404."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.headers = {}
            mock_get.return_value = mock_resp

            mock_fitz_mod = MagicMock()
            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = openreview_source.fetch_full_text("nonexistent123")

        assert result is None

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_full_text_request_exception(self, mock_sleep, openreview_source):
        """fetch_full_text returns None on request exception."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_get.side_effect = requests.RequestException("Timeout")

            mock_fitz_mod = MagicMock()
            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = openreview_source.fetch_full_text("note123ABC")

        assert result is None

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_full_text_extraction_fails(self, mock_sleep, openreview_source):
        """fetch_full_text returns None when text extraction raises."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"%PDF-fake"
            mock_resp.headers = {"Content-Type": "application/pdf"}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            mock_fitz_mod = MagicMock()
            mock_fitz_mod.open.side_effect = RuntimeError("Corrupt PDF")

            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = openreview_source.fetch_full_text("note123ABC")

        assert result is None

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_full_text_empty_extraction(self, mock_sleep, openreview_source):
        """fetch_full_text returns None when PDF has no text."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"%PDF-fake"
            mock_resp.headers = {"Content-Type": "application/pdf"}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            mock_fitz_mod = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = ""
            mock_doc = MagicMock()
            mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
            mock_fitz_mod.open.return_value = mock_doc

            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = openreview_source.fetch_full_text("note123ABC")

        assert result is None

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_full_text_html_response(self, mock_sleep, openreview_source):
        """fetch_full_text returns None when response is HTML error page."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"<html>Error</html>"
            mock_resp.headers = {"Content-Type": "text/html"}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            mock_fitz_mod = MagicMock()
            with patch.dict(sys.modules, {"fitz": mock_fitz_mod}):
                result = openreview_source.fetch_full_text("note123ABC")

        assert result is None

    @patch("backend.shared.pdf.extract_text_from_pdf")
    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_full_text_rate_limited_then_succeeds(self, mock_sleep, mock_extract, openreview_source):
        """fetch_full_text retries after 429 and succeeds."""
        with patch.object(openreview_source._session, "get") as mock_get:
            rate_resp = MagicMock()
            rate_resp.status_code = 429
            rate_resp.headers = {"Retry-After": "3"}

            success_resp = MagicMock()
            success_resp.status_code = 200
            success_resp.content = b"%PDF-fake"
            success_resp.headers = {"Content-Type": "application/pdf"}
            success_resp.raise_for_status = MagicMock()

            mock_get.side_effect = [rate_resp, success_resp]

            mock_extract.return_value = "Retried text."

            result = openreview_source.fetch_full_text("note123ABC")

        assert result == "Retried text."

    def test_fetch_full_text_no_fitz_installed(self):
        """fetch_full_text returns None if pymupdf is not importable."""
        source = OpenReviewSource()
        with patch.dict(sys.modules, {"fitz": None}):
            result = source.fetch_full_text("note123ABC")
        assert result is None

    @patch("backend.shared.pdf.extract_text_from_pdf")
    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_full_text_multi_page(self, mock_sleep, mock_extract, openreview_source):
        """fetch_full_text joins multiple pages with double newline."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"%PDF-fake"
            mock_resp.headers = {"Content-Type": "application/pdf"}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            mock_extract.return_value = "Abstract section\n\nMethods section"

            result = openreview_source.fetch_full_text("note123ABC")

        assert result == "Abstract section\n\nMethods section"


# ─── _get_review_score and _fetch_average_review_score tests ─────────────────


class TestReviewScoring:
    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_average_review_score_success(self, mock_sleep, openreview_source):
        """_fetch_average_review_score computes average from review notes."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "notes": [
                    {"content": {"rating": {"value": "8: Strong Accept"}}},
                    {"content": {"rating": {"value": "6: Weak Accept"}}},
                    {"content": {"rating": {"value": "7: Accept"}}},
                ]
            }
            mock_get.return_value = mock_resp

            result = openreview_source._fetch_average_review_score("paper123")

        assert result == 7.0

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_average_review_score_no_reviews(self, mock_sleep, openreview_source):
        """_fetch_average_review_score returns None when no reviews have ratings."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"notes": []}
            mock_get.return_value = mock_resp

            result = openreview_source._fetch_average_review_score("paper123")

        assert result is None

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_average_review_score_api_error(self, mock_sleep, openreview_source):
        """_fetch_average_review_score returns None on API error."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_get.return_value = mock_resp

            result = openreview_source._fetch_average_review_score("paper123")

        assert result is None

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_average_review_score_with_recommendation_field(self, mock_sleep, openreview_source):
        """_fetch_average_review_score handles 'recommendation' field."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "notes": [
                    {"content": {"recommendation": {"value": "5"}}},
                ]
            }
            mock_get.return_value = mock_resp

            result = openreview_source._fetch_average_review_score("paper123")

        assert result == 5.0

    @patch("backend.sources.openreview.time.sleep")
    def test_fetch_average_review_score_with_fraction_format(self, mock_sleep, openreview_source):
        """_fetch_average_review_score handles '7/10' format ratings."""
        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "notes": [
                    {"content": {"rating": {"value": "7/10"}}},
                    {"content": {"rating": {"value": "9/10"}}},
                ]
            }
            mock_get.return_value = mock_resp

            result = openreview_source._fetch_average_review_score("paper123")

        assert result == 8.0

    def test_get_review_score_from_content_rating_dict(self, openreview_source):
        """_get_review_score extracts score from content rating dict."""
        note = {"id": "test1"}
        content = {"rating": {"value": 7.5}}
        result = openreview_source._get_review_score(note, content)
        assert result == 7.5

    def test_get_review_score_from_content_rating_plain(self, openreview_source):
        """_get_review_score handles plain numeric rating."""
        note = {"id": "test1"}
        content = {"rating": 8}
        result = openreview_source._get_review_score(note, content)
        assert result == 8.0

    @patch("backend.sources.openreview.time.sleep")
    def test_get_review_score_falls_back_to_fetch(self, mock_sleep, openreview_source):
        """_get_review_score fetches reviews when no embedded rating."""
        note = {"id": "test1"}
        content = {}  # No rating field

        with patch.object(openreview_source._session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "notes": [{"content": {"rating": {"value": "6: Weak Accept"}}}]
            }
            mock_get.return_value = mock_resp

            result = openreview_source._get_review_score(note, content)

        assert result == 6.0

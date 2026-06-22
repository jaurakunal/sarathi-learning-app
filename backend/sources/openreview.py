"""OpenReview paper source — discovery via OpenReview API v2, full-text via PDF."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from backend.shared.models import Area

logger = logging.getLogger(__name__)

# OpenReview is generous but let's be polite — 1 req/sec baseline
_OPENREVIEW_DELAY_S = 1.0

# Top ML venues on OpenReview we care about
_VENUES = [
    "ICLR.cc/2026/Conference",
    "ICLR.cc/2025/Conference",
    "NeurIPS.cc/2026/Conference",
    "NeurIPS.cc/2025/Conference",
    "ICML.cc/2026/Conference",
    "ICML.cc/2025/Conference",
]

_API_BASE = "https://api2.openreview.net"
_SEARCH_URL = f"{_API_BASE}/notes/search"
_NOTES_URL = f"{_API_BASE}/notes"
_PDF_BASE = "https://openreview.net/pdf"


def _build_search_terms(areas: list[Area]) -> list[str]:
    """Build search term strings from areas — one per area for targeted queries.

    Each term combines the area label with just_right keywords so the OpenReview
    free-text search can match relevant papers.
    """
    terms: list[str] = []
    for area in areas:
        parts: list[str] = []
        if area.label:
            parts.append(area.label)
        for kw in area.just_right[:4]:  # Cap to avoid query bloat
            parts.append(kw)
        if parts:
            terms.append(" ".join(parts))
    return terms


def _epoch_ms(dt: datetime) -> int:
    """Convert a datetime to epoch milliseconds (OpenReview uses cdate in ms)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class OpenReviewSource:
    """Discovers papers from OpenReview and fetches full text via PDF extraction."""

    name = "openreview"

    def __init__(self, max_results_per_query: int = 50):
        self._max_results = max_results_per_query
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": "Sarathi-ResearchBot/0.1 (academic research tool)"}
        )

    def discover(self, areas: list[Area], since: datetime, queries: list[str] | None = None) -> list[dict]:
        """Query OpenReview for papers matching areas published since `since`.

        Uses two strategies:
        1. Free-text search with pre-generated queries via /notes/search
        2. Venue-based queries for recent top conferences
        """
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        search_terms = queries if queries else _build_search_terms(areas)
        if not search_terms:
            logger.warning("OpenReviewSource.discover: no search terms")
            return []

        seen_ids: set[str] = set()
        results: list[dict] = []

        # Strategy 1: Free-text search across OpenReview
        for term in search_terms:
            papers = self._search_by_term(term, since)
            for p in papers:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    results.append(p)

        # Strategy 2: Venue-based discovery for recent top conferences
        # Use only first 3 queries to keep request count reasonable (3 queries × 6 venues = 18 max)
        venue_terms = search_terms[:3]
        rate_limited = False
        for venue in _VENUES:
            if rate_limited:
                break
            for term in venue_terms:
                if rate_limited:
                    break
                papers = self._search_by_venue(venue, term, since)
                if papers is None:
                    rate_limited = True
                    break
                for p in papers:
                    if p["id"] not in seen_ids:
                        seen_ids.add(p["id"])
                        results.append(p)

        logger.info("OpenReviewSource.discover found %d papers", len(results))
        return results

    def fetch_full_text(self, paper_id: str) -> Optional[str]:
        """Download the PDF for an OpenReview paper and extract text.

        Args:
            paper_id: The OpenReview forum/note ID (e.g. 'abc123XYZ').

        Returns:
            Extracted text from the PDF, or None if extraction fails.
        """
        from backend.shared.pdf import extract_text_from_pdf

        pdf_url = f"{_PDF_BASE}?id={paper_id}"
        pdf_bytes = self._download_pdf(pdf_url)
        if pdf_bytes is None:
            return None

        return extract_text_from_pdf(pdf_bytes)

    # ─── Private helpers ─────────────────────────────────────────────

    def _search_by_term(self, term: str, since: datetime) -> list[dict]:
        """Free-text search via /notes/search endpoint."""
        params = {
            "term": term,
            "limit": self._max_results,
            "sort": "cdate:desc",
        }

        try:
            time.sleep(_OPENREVIEW_DELAY_S)
            resp = self._session.get(_SEARCH_URL, params=params, timeout=30)

            if resp.status_code == 429:
                logger.warning("OpenReview rate-limited on search, skipping")
                return []

            if resp.status_code != 200:
                logger.warning(
                    "OpenReview search returned %d for term '%s': %s",
                    resp.status_code,
                    term,
                    resp.text[:200],
                )
                return []

            data = resp.json()
            notes = data.get("notes", [])
            return self._normalize_notes(notes, since)

        except requests.RequestException:
            logger.exception("OpenReview search request failed for term: %s", term)
            return []
        except (ValueError, KeyError):
            logger.exception("OpenReview search response parse failed for term: %s", term)
            return []

    def _search_by_venue(self, venue: str, term: str, since: datetime) -> list[dict] | None:
        """Query papers from a specific venue with keyword filtering.

        Returns None on rate limit (signal to caller to stop all queries).
        """
        params = {
            "content.venue": venue,
            "term": term,
            "limit": self._max_results,
            "sort": "cdate:desc",
        }

        try:
            time.sleep(_OPENREVIEW_DELAY_S)
            resp = self._session.get(_NOTES_URL, params=params, timeout=30)

            if resp.status_code == 429:
                logger.warning("OpenReview rate-limited on venue query, stopping all queries")
                return None

            if resp.status_code != 200:
                logger.warning(
                    "OpenReview venue query returned %d for '%s' / '%s': %s",
                    resp.status_code,
                    venue,
                    term,
                    resp.text[:200],
                )
                return []

            data = resp.json()
            notes = data.get("notes", [])
            return self._normalize_notes(notes, since)

        except requests.RequestException:
            logger.exception(
                "OpenReview venue request failed for %s / %s", venue, term
            )
            return []
        except (ValueError, KeyError):
            logger.exception(
                "OpenReview venue response parse failed for %s / %s", venue, term
            )
            return []

    def _normalize_notes(self, notes: list[dict], since: datetime) -> list[dict]:
        """Convert raw OpenReview note dicts to our normalized format."""
        since_ms = _epoch_ms(since)
        results: list[dict] = []

        for note in notes:
            try:
                # cdate is creation date in epoch ms
                cdate = note.get("cdate") or note.get("tcdate", 0)
                if cdate < since_ms:
                    continue

                note_id = note.get("id", "")
                if not note_id:
                    continue

                content = note.get("content", {})

                # Title — v2 API wraps values in {value: ...}
                title_field = content.get("title", {})
                title = (
                    title_field.get("value", "")
                    if isinstance(title_field, dict)
                    else str(title_field)
                )
                if not title:
                    continue

                # Authors
                authors_field = content.get("authors", {})
                if isinstance(authors_field, dict):
                    authors = authors_field.get("value", [])
                elif isinstance(authors_field, list):
                    authors = authors_field
                else:
                    authors = []

                # Abstract
                abstract_field = content.get("abstract", {})
                abstract = (
                    abstract_field.get("value", "")
                    if isinstance(abstract_field, dict)
                    else str(abstract_field) if abstract_field else ""
                )

                # Venue
                venue_field = content.get("venue", content.get("venueid", {}))
                if isinstance(venue_field, dict):
                    venue = venue_field.get("value", "")
                else:
                    venue = str(venue_field) if venue_field else ""

                # Convert cdate to ISO datetime
                published_dt = datetime.fromtimestamp(cdate / 1000, tz=timezone.utc)

                # URL
                url = f"https://openreview.net/forum?id={note_id}"

                # Peer review score — attempt to get from the note's rating field
                peer_review_score = self._get_review_score(note, content)

                results.append(
                    {
                        "id": note_id,
                        "source": "openreview",
                        "title": title,
                        "authors": authors if isinstance(authors, list) else [],
                        "abstract": abstract,
                        "url": url,
                        "published": published_dt.isoformat(),
                        "venue": venue,
                        "peer_review_score": peer_review_score,
                    }
                )
            except Exception:
                logger.debug(
                    "Skipping malformed OpenReview note: %s",
                    note.get("id", "unknown"),
                    exc_info=True,
                )
                continue

        return results

    def _get_review_score(self, note: dict, content: dict) -> Optional[float]:
        """Try to extract a peer review score from the note.

        OpenReview stores reviews as separate notes replying to the submission.
        The submission itself sometimes has an aggregated rating in its content.
        We try the easy path first (content.rating), then fall back to fetching
        reviews for this paper.
        """
        # Quick path: some venues embed overall rating in the submission note
        rating_field = content.get("rating", content.get("recommendation", {}))
        if isinstance(rating_field, dict):
            val = rating_field.get("value")
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        elif rating_field:
            try:
                return float(rating_field)
            except (ValueError, TypeError):
                pass

        # Heavier path: fetch reviews for this paper
        note_id = note.get("id", "")
        if not note_id:
            return None

        return self._fetch_average_review_score(note_id)

    def _fetch_average_review_score(self, paper_id: str) -> Optional[float]:
        """Fetch review notes for a paper and compute average rating.

        Returns None if reviews aren't available or the request fails.
        We keep this best-effort to avoid slowing down discovery.
        """
        # Use a shorter timeout and don't retry — this is supplemental data
        params = {
            "forum": paper_id,
            "select": "content.rating,content.recommendation,content.soundness",
            "limit": 20,
        }

        try:
            time.sleep(_OPENREVIEW_DELAY_S)
            resp = self._session.get(_NOTES_URL, params=params, timeout=15)

            if resp.status_code != 200:
                return None

            data = resp.json()
            notes = data.get("notes", [])

            ratings: list[float] = []
            for review_note in notes:
                review_content = review_note.get("content", {})

                # Look for rating or recommendation field
                for field_name in ("rating", "recommendation", "overall_assessment"):
                    field = review_content.get(field_name, {})
                    if isinstance(field, dict):
                        val = field.get("value")
                    else:
                        val = field

                    if val is not None:
                        # Ratings often look like "8: Strong Accept" — grab the number
                        val_str = str(val).strip()
                        # Try to extract leading number
                        num_part = val_str.split(":")[0].split("/")[0].strip()
                        try:
                            ratings.append(float(num_part))
                            break
                        except ValueError:
                            continue

            if ratings:
                return round(sum(ratings) / len(ratings), 2)

            return None

        except Exception:
            logger.debug(
                "Could not fetch review scores for %s", paper_id, exc_info=True
            )
            return None

    def _download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF from OpenReview with rate-limit courtesy."""
        logger.info("Downloading PDF: %s", url)
        time.sleep(_OPENREVIEW_DELAY_S)

        try:
            resp = self._session.get(url, timeout=60)

            if resp.status_code == 429:
                logger.warning("OpenReview rate-limited on PDF download, skipping")
                return None

            if resp.status_code == 404:
                logger.warning("PDF not found at %s", url)
                return None

            resp.raise_for_status()

            # Verify we got a PDF and not an HTML error page
            content_type = resp.headers.get("Content-Type", "")
            if "pdf" not in content_type and not resp.content[:5] == b"%PDF-":
                logger.warning(
                    "Response from %s does not appear to be a PDF (Content-Type: %s)",
                    url,
                    content_type,
                )
                return None

            return resp.content

        except requests.RequestException:
            logger.exception("Failed to download PDF from %s", url)
            return None


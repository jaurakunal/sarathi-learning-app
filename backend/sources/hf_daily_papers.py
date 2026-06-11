"""Hugging Face Daily Papers source — discovery via HF API and full-text via arXiv PDF."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from backend.shared.models import Area

logger = logging.getLogger(__name__)

# Be polite to HF and arXiv APIs
_HF_DELAY_S = 1.0
_ARXIV_PDF_DELAY_S = 3.0

_HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"


def _extract_keywords(areas: list[Area]) -> list[str]:
    """Extract all searchable keywords from areas for relevance filtering.

    Collects each area's label and just_right terms into a flat list of
    lowercased keywords for substring matching against paper text.
    """
    keywords: list[str] = []
    for area in areas:
        if area.label:
            keywords.append(area.label.lower())
        for term in area.just_right:
            keywords.append(term.lower())
    return keywords


def _paper_matches_keywords(title: str, abstract: str, keywords: list[str]) -> bool:
    """Check if a paper's title or abstract contains any of the keywords.

    This is a coarse filter — the LLM triage step does fine-grained scoring later.
    """
    if not keywords:
        return True  # No keywords means accept all

    text = f"{title} {abstract}".lower()
    return any(kw in text for kw in keywords)


class HFDailyPapersSource:
    """Discovers papers from Hugging Face Daily Papers and fetches full text via arXiv."""

    name = "hf_daily_papers"

    def __init__(self, max_papers: int = 100):
        self._max_papers = max_papers

    def discover(self, areas: list[Area], since: datetime, queries: list[str] | None = None) -> list[dict]:
        """Query HF Daily Papers API for papers matching areas published since `since`.

        Note: HF Daily Papers doesn't support search queries — it returns all daily
        papers and we filter by keyword matching. The queries param is used as additional
        keywords for matching if provided.

        Returns normalized dicts:
            {id, source, title, authors, abstract, url, published, upvotes}
        """
        if not areas:
            logger.warning("HFDailyPapersSource.discover: no areas provided")
            return []

        # Ensure since is timezone-aware for comparison
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        keywords = _extract_keywords(areas)
        if queries:
            keywords.extend([q.lower() for q in queries])
        if not keywords:
            logger.warning("HFDailyPapersSource.discover: no keywords extracted from areas")
            return []

        logger.info(
            "HFDailyPapersSource.discover: fetching papers since %s with keywords: %s",
            since.isoformat(),
            keywords,
        )

        # Fetch papers from HF API
        raw_papers = self._fetch_daily_papers()
        if not raw_papers:
            return []

        results: list[dict] = []

        for entry in raw_papers:
            try:
                paper_data = entry.get("paper", {})
                paper_id = paper_data.get("id", "")

                # Parse the published date
                published_str = entry.get("publishedAt") or paper_data.get("publishedAt", "")
                if not published_str:
                    continue

                published_dt = self._parse_datetime(published_str)
                if published_dt is None:
                    continue

                if published_dt < since:
                    continue

                title = entry.get("title", "") or paper_data.get("title", "")
                abstract = paper_data.get("summary", "")

                # Coarse relevance filter using area keywords
                if not _paper_matches_keywords(title, abstract, keywords):
                    continue

                # Extract authors
                authors = []
                for author in paper_data.get("authors", []):
                    if isinstance(author, dict):
                        name = author.get("name", "")
                        if name:
                            authors.append(name)
                    elif isinstance(author, str):
                        authors.append(author)

                # Upvotes are a HF-specific social signal
                upvotes = entry.get("paper", {}).get("upvotes", 0)
                if not upvotes:
                    upvotes = entry.get("numUpvotes", 0)

                # Build the HF paper page URL
                hf_url = f"https://huggingface.co/papers/{paper_id}" if paper_id else ""

                results.append(
                    {
                        "id": paper_id,
                        "source": "hf_daily_papers",
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "url": hf_url,
                        "published": published_dt.isoformat(),
                        "upvotes": upvotes,
                    }
                )

                if len(results) >= self._max_papers:
                    break

            except Exception:
                logger.exception("HFDailyPapersSource: error processing paper entry")
                continue

        logger.info("HFDailyPapersSource.discover found %d papers", len(results))
        return results

    def fetch_full_text(self, paper_id: str) -> Optional[str]:
        """Download the PDF from arXiv (HF daily papers are typically arXiv papers) and extract text.

        Args:
            paper_id: The arXiv paper ID (e.g. '2301.07041').

        Returns:
            Extracted text from the PDF, or None if extraction fails.
        """
        from backend.shared.pdf import extract_text_from_pdf

        if not paper_id:
            logger.warning("HFDailyPapersSource.fetch_full_text: empty paper_id")
            return None

        # HF Daily Papers are arXiv papers; the paper_id is the arXiv ID
        pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"

        # Download the PDF
        pdf_bytes = self._download_pdf(pdf_url)
        if pdf_bytes is None:
            return None

        # Extract text
        return extract_text_from_pdf(pdf_bytes)

    def _fetch_daily_papers(self) -> list[dict]:
        """Fetch the daily papers list from Hugging Face API."""
        logger.info("Fetching HF Daily Papers from %s", _HF_DAILY_PAPERS_URL)
        time.sleep(_HF_DELAY_S)

        try:
            resp = requests.get(
                _HF_DAILY_PAPERS_URL,
                timeout=30,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Some API versions wrap results in a key
                return data.get("papers", data.get("results", []))
            else:
                logger.warning("HF API returned unexpected data type: %s", type(data))
                return []

        except Exception:
            logger.exception("Failed to fetch HF Daily Papers")
            return []

    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse an ISO-format datetime string, handling various formats."""
        try:
            # Handle 'Z' suffix (common in API responses)
            dt_str = dt_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            logger.debug("Could not parse datetime: %s", dt_str)
            return None

    def _download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF from the given URL with rate-limit courtesy."""
        logger.info("Downloading PDF: %s", url)
        time.sleep(_ARXIV_PDF_DELAY_S)  # Rate-limit courtesy for arXiv

        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()

            # Sanity check: arXiv sometimes returns HTML error pages
            content_type = resp.headers.get("Content-Type", "")
            if "pdf" not in content_type and not resp.content[:5] == b"%PDF-":
                logger.warning(
                    "Response does not appear to be a PDF (Content-Type: %s)",
                    content_type,
                )
                return None

            return resp.content
        except requests.RequestException:
            logger.exception("Failed to download PDF from %s", url)
            return None


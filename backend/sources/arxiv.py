"""arXiv paper source — discovery via arXiv API and full-text via PDF extraction."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import arxiv
import requests

from backend.shared.models import Area

logger = logging.getLogger(__name__)

# arXiv rate-limits to 1 request per 3 seconds
_ARXIV_DELAY_S = 3.0


def _build_query(areas: list[Area]) -> str:
    """Build an arXiv search query using LLM-generated terms.

    Uses an LLM to generate proper academic search queries from the area
    descriptions, then OR-joins them for broad coverage.
    """
    from backend.shared.query_gen import generate_all_queries

    queries = generate_all_queries(areas)
    if not queries:
        return ""

    # OR-join all generated queries — each is already a focused 2-4 word search
    return " OR ".join(f'all:"{q}"' for q in queries)


class ArxivSource:
    """Discovers papers from arXiv and fetches full text via PDF extraction."""

    name = "arxiv"

    def __init__(self, max_results_per_query: int = 50):
        self._max_results = max_results_per_query

    def discover(self, areas: list[Area], since: datetime) -> list[dict]:
        """Query arXiv for papers matching areas published since `since`.

        Returns normalized dicts:
            {id, source, title, authors, abstract, url, published, arxiv_categories}
        """
        query = _build_query(areas)
        if not query:
            logger.warning("ArxivSource.discover: empty query from areas")
            return []

        logger.info("ArxivSource query: %s", query)

        # Ensure since is timezone-aware for comparison
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        client = arxiv.Client(
            page_size=100,
            delay_seconds=_ARXIV_DELAY_S,
            num_retries=3,
        )

        search = arxiv.Search(
            query=query,
            max_results=self._max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        results: list[dict] = []

        try:
            for paper in client.results(search):
                # Filter by publication date
                published_dt = paper.published
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(tzinfo=timezone.utc)

                if published_dt < since:
                    # Results are sorted newest-first, so once we hit one
                    # older than `since` we can stop
                    break

                results.append(
                    {
                        "id": paper.entry_id,
                        "source": "arxiv",
                        "title": paper.title,
                        "authors": [a.name for a in paper.authors],
                        "abstract": paper.summary,
                        "url": paper.entry_id,
                        "published": published_dt.isoformat(),
                        "arxiv_categories": paper.categories,
                    }
                )
        except Exception:
            logger.exception("ArxivSource.discover failed during arXiv query")

        logger.info("ArxivSource.discover found %d papers", len(results))
        return results

    def fetch_full_text(self, paper_id: str) -> Optional[str]:
        """Download the PDF for an arXiv paper and extract text.

        Args:
            paper_id: The arXiv paper ID (e.g. '2301.07041') or full entry URL.

        Returns:
            Extracted text from the PDF, or None if extraction fails.
        """
        from backend.shared.pdf import extract_text_from_pdf

        pdf_url = self._resolve_pdf_url(paper_id)
        if not pdf_url:
            return None

        pdf_bytes = self._download_pdf(pdf_url)
        if pdf_bytes is None:
            return None

        return extract_text_from_pdf(pdf_bytes)

    def _resolve_pdf_url(self, paper_id: str) -> Optional[str]:
        """Convert a paper ID or entry URL to a PDF download URL."""
        # If it's already a full URL like http://arxiv.org/abs/2301.07041v1
        if paper_id.startswith("http"):
            # Convert abs URL to pdf URL
            url = paper_id.replace("/abs/", "/pdf/")
            if not url.endswith(".pdf"):
                url += ".pdf"
            return url

        # Bare ID like '2301.07041' or '2301.07041v1'
        return f"https://arxiv.org/pdf/{paper_id}.pdf"

    def _download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF from the given URL with rate-limit courtesy."""
        logger.info("Downloading PDF: %s", url)
        time.sleep(_ARXIV_DELAY_S)  # Rate-limit courtesy

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


"""Semantic Scholar paper source — discovery via S2 Academic Graph API, full-text via open access PDFs."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from backend.shared.models import Area

logger = logging.getLogger(__name__)

# Semantic Scholar rate-limits free tier to 100 requests per 5 minutes.
# That's ~1 request per 3 seconds on average; we use a conservative delay.
_S2_DELAY_S = 3.0

_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"

_S2_SEARCH_FIELDS = (
    "paperId,title,authors,abstract,url,"
    "publicationDate,fieldsOfStudy,citationCount,influentialCitationCount"
)


def _build_queries(areas: list[Area]) -> list[str]:
    """Build one search query string per area from label + just_right keywords.

    Each query combines the area label with its just_right keywords for
    specificity. We return one query per area to stay within S2's query
    length limits and to respect rate limiting.
    """
    queries: list[str] = []

    for area in areas:
        terms: list[str] = []

        if area.label:
            terms.append(area.label)

        for kw in area.just_right:
            terms.append(kw)

        if terms:
            # S2 search works best with simple space-separated terms
            # Limit to first 5 terms to avoid overly restrictive queries
            query = " ".join(terms[:5])
            queries.append(query)

    return queries


class SemanticScholarSource:
    """Discovers papers from Semantic Scholar and fetches full text via open access PDFs."""

    name = "semantic_scholar"

    def __init__(self, max_results_per_query: int = 50, api_key: Optional[str] = None):
        self._max_results = max_results_per_query
        self._session = requests.Session()
        if api_key:
            self._session.headers["x-api-key"] = api_key

    def discover(self, areas: list[Area], since: datetime) -> list[dict]:
        """Query Semantic Scholar for papers matching areas published since `since`.

        Returns normalized dicts:
            {id, source, title, authors, abstract, url, published,
             fields_of_study, citation_count, influential_citation_count}
        """
        queries = _build_queries(areas)
        if not queries:
            logger.warning("SemanticScholarSource.discover: no queries from areas")
            return []

        # Ensure since is timezone-aware for comparison
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        results: list[dict] = []
        seen_ids: set[str] = set()

        for query in queries:
            papers = self._search(query, since)
            for paper in papers:
                paper_id = paper.get("id")
                if paper_id and paper_id not in seen_ids:
                    seen_ids.add(paper_id)
                    results.append(paper)

        logger.info("SemanticScholarSource.discover found %d papers", len(results))
        return results

    def _search(self, query: str, since: datetime) -> list[dict]:
        """Execute a single paginated search query against S2 API."""
        logger.info("SemanticScholarSource query: %s", query)

        results: list[dict] = []
        offset = 0
        page_size = min(100, self._max_results)  # S2 max is 100 per page

        while offset < self._max_results:
            time.sleep(_S2_DELAY_S)  # Rate-limit courtesy

            params = {
                "query": query,
                "fields": _S2_SEARCH_FIELDS,
                "offset": offset,
                "limit": page_size,
            }

            try:
                resp = self._session.get(
                    _S2_SEARCH_URL, params=params, timeout=30
                )

                # Skip on rate limit — shared pool, not worth waiting
                if resp.status_code == 429:
                    logger.warning(
                        "S2 rate limited (shared unauthenticated pool), skipping source"
                    )
                    return results

                resp.raise_for_status()
                data = resp.json()

            except requests.RequestException:
                logger.exception(
                    "SemanticScholarSource._search failed for query: %s", query
                )
                break

            papers = data.get("data", [])
            if not papers:
                break

            for paper in papers:
                normalized = self._normalize_paper(paper, since)
                if normalized is not None:
                    results.append(normalized)

            # Check if there are more results
            total = data.get("total", 0)
            offset += page_size
            try:
                if offset >= int(total):
                    break
            except (TypeError, ValueError):
                break

        return results

    def _normalize_paper(self, paper: dict, since: datetime) -> Optional[dict]:
        """Normalize an S2 paper dict into our standard format.

        Returns None if the paper should be filtered out (e.g. published before `since`).
        """
        # Filter by publication date
        pub_date_str = paper.get("publicationDate")
        if not pub_date_str:
            # No publication date available — skip since we cannot verify recency
            return None

        try:
            pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            logger.debug("Could not parse publication date: %s", pub_date_str)
            return None

        if pub_date < since:
            return None

        # Extract authors
        authors_raw = paper.get("authors") or []
        authors = [a.get("name", "") for a in authors_raw if a.get("name")]

        # Build the paper URL — prefer the S2 url field, fall back to constructing one
        url = paper.get("url") or f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}"

        return {
            "id": paper.get("paperId", ""),
            "source": "semantic_scholar",
            "title": paper.get("title", ""),
            "authors": authors,
            "abstract": paper.get("abstract") or "",
            "url": url,
            "published": pub_date.isoformat(),
            "fields_of_study": paper.get("fieldsOfStudy") or [],
            "citation_count": paper.get("citationCount") or 0,
            "influential_citation_count": paper.get("influentialCitationCount") or 0,
        }

    def fetch_full_text(self, paper_id: str) -> Optional[str]:
        """Fetch the full text of a paper via its open access PDF.

        Args:
            paper_id: The Semantic Scholar paper ID (40-char hex hash).

        Returns:
            Extracted text from the PDF, or None if no open access PDF is available.
        """
        from backend.shared.pdf import extract_text_from_pdf

        pdf_url = self._get_open_access_pdf_url(paper_id)
        if not pdf_url:
            return None

        pdf_bytes = self._download_pdf(pdf_url)
        if pdf_bytes is None:
            return None

        return extract_text_from_pdf(pdf_bytes)

    def _get_open_access_pdf_url(self, paper_id: str) -> Optional[str]:
        """Query S2 for the open access PDF URL of a paper."""
        time.sleep(_S2_DELAY_S)  # Rate-limit courtesy

        url = f"{_S2_PAPER_URL}/{paper_id}"
        params = {"fields": "openAccessPdf"}

        try:
            resp = self._session.get(url, params=params, timeout=30)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logger.warning(
                    "S2 rate limited on PDF lookup, waiting %d seconds",
                    retry_after,
                )
                time.sleep(retry_after)
                resp = self._session.get(url, params=params, timeout=30)
                resp.raise_for_status()
            else:
                resp.raise_for_status()

            data = resp.json()
            open_access = data.get("openAccessPdf")

            if open_access and open_access.get("url"):
                return open_access["url"]

            logger.info(
                "No open access PDF available for paper %s", paper_id
            )
            return None

        except requests.RequestException:
            logger.exception(
                "Failed to fetch open access PDF info for paper %s", paper_id
            )
            return None

    def _download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF from the given URL."""
        logger.info("Downloading PDF: %s", url)
        time.sleep(_S2_DELAY_S)  # Rate-limit courtesy

        try:
            resp = self._session.get(url, timeout=60)
            resp.raise_for_status()

            # Sanity check: verify we got a PDF
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


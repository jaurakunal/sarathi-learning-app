"""Paper source: Papers With Code (paperswithcode.com).

Papers that have code implementations — ideal for a practitioner who
builds things. Free API, no auth required, generous rate limits.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://paperswithcode.com/api/v1"
_DELAY_S = 1.5
_MAX_RESULTS_PER_QUERY = 20


class PapersWithCodeSource:
    """Discovers papers from Papers With Code search API."""

    name = "papers_with_code"

    def __init__(self, max_results_per_query: int = _MAX_RESULTS_PER_QUERY):
        self._max_results = max_results_per_query

    def discover(self, areas: list, since: datetime, queries: list[str] | None = None) -> list[dict]:
        """Search Papers With Code for papers matching queries.

        Args:
            areas: User's research areas (used as fallback keywords)
            since: Only return papers published after this date
            queries: Pre-generated search queries

        Returns:
            List of normalized paper dicts
        """
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        search_terms = queries or [a.label if hasattr(a, 'label') else str(a) for a in areas]
        if not search_terms:
            return []

        all_papers: list[dict] = []
        seen_ids: set[str] = set()

        for term in search_terms[:10]:  # Cap at 10 queries
            time.sleep(_DELAY_S)
            papers = self._search(term, since)
            for paper in papers:
                pid = paper.get("id", "")
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_papers.append(paper)

        logger.info("PapersWithCode: %d unique papers from %d queries", len(all_papers), min(len(search_terms), 10))
        return all_papers

    def _search(self, query: str, since: datetime) -> list[dict]:
        """Search for papers matching a query."""
        params = {
            "q": query,
            "page": 1,
            "items_per_page": self._max_results,
        }

        try:
            resp = requests.get(f"{_API_BASE}/papers/", params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("PapersWithCode: search failed for query '%s'", query)
            return []

        data = resp.json()
        results = data.get("results", [])
        papers: list[dict] = []

        for item in results:
            paper = self._normalize(item, since)
            if paper:
                papers.append(paper)

        return papers

    def _normalize(self, item: dict, since: datetime) -> Optional[dict]:
        """Normalize a PapersWithCode API result to our Paper format."""
        title = item.get("title", "")
        abstract = item.get("abstract", "")
        paper_url = item.get("url_abs", "") or item.get("paper_url", "")
        published = item.get("published", "")

        if not title:
            return None

        # Parse publication date
        if published:
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < since:
                    return None
            except (ValueError, TypeError):
                pass  # Keep paper if date is unparseable

        # Build a stable ID from the URL or title
        paper_id = ""
        if paper_url:
            # Extract arXiv ID if present
            if "arxiv.org/abs/" in paper_url:
                paper_id = paper_url.split("/abs/")[-1].split("v")[0]
            else:
                # Use the PwC paper slug
                paper_id = f"pwc:{item.get('id', '')}" if item.get('id') else f"pwc:{title[:50]}"
        else:
            paper_id = f"pwc:{item.get('id', title[:50])}"

        # Get authors
        authors = []
        if item.get("authors"):
            authors = [a if isinstance(a, str) else a.get("name", "") for a in item["authors"][:5]]

        return {
            "id": paper_id,
            "title": title.strip(),
            "abstract": abstract[:2000] if abstract else "",
            "authors": authors,
            "url": paper_url or f"https://paperswithcode.com/paper/{item.get('id', '')}",
            "source": self.name,
            "published_at": published or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "has_code": True,
        }

    def fetch_full_text(self, paper_id: str) -> Optional[str]:
        """Fetch full text. For arXiv-backed papers, use arXiv PDF extraction."""
        if paper_id.startswith("pwc:"):
            return None  # Non-arXiv papers don't have easy full-text access

        # arXiv-based papers — delegate to arXiv source
        from backend.sources.arxiv import ArxivSource
        return ArxivSource().fetch_full_text(paper_id)

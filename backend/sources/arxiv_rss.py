"""Paper source: arXiv RSS feeds (daily new submissions by category).

Unlike the arXiv search API, RSS feeds are static daily dumps with zero
rate-limit risk. They catch papers that keyword search misses (new
terminology, novel framing) because they return ALL submissions in a category.
The relevance filter downstream handles selecting what's actually interesting.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# arXiv RSS categories relevant to AI agents / memory / security
DEFAULT_CATEGORIES = ["cs.AI", "cs.CL", "cs.MA", "cs.LG"]

_RSS_BASE_URL = "http://export.arxiv.org/rss"
_DELAY_S = 2.0


class ArxivRssSource:
    """Discovers papers from arXiv RSS feeds (daily new submissions)."""

    name = "arxiv_rss"

    def __init__(self, categories: list[str] | None = None):
        self._categories = categories or DEFAULT_CATEGORIES

    def discover(self, areas: list, since: datetime, queries: list[str] | None = None) -> list[dict]:
        """Fetch RSS feeds for configured categories and return new papers.

        Args:
            areas: User's research areas (unused — RSS is category-based, not query-based)
            since: Only return papers published after this date
            queries: Unused (RSS feeds are not searchable)

        Returns:
            List of normalized paper dicts
        """
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        all_papers: list[dict] = []
        seen_ids: set[str] = set()

        for category in self._categories:
            time.sleep(_DELAY_S)
            papers = self._fetch_category(category, since)
            for paper in papers:
                pid = paper.get("id", "")
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_papers.append(paper)

            logger.info("ArxivRSS category %s: %d papers", category, len(papers))

        logger.info("ArxivRSS total: %d unique papers from %d categories", len(all_papers), len(self._categories))
        return all_papers

    def _fetch_category(self, category: str, since: datetime) -> list[dict]:
        """Fetch and parse RSS feed for one category."""
        url = f"{_RSS_BASE_URL}/{category}"

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception:
            logger.warning("ArxivRSS: failed to fetch %s", url)
            return []

        return self._parse_rss(resp.text, since, category)

    def _parse_rss(self, xml_text: str, since: datetime, category: str) -> list[dict]:
        """Parse RSS XML into normalized paper dicts."""
        results: list[dict] = []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning("ArxivRSS: failed to parse XML for %s", category)
            return []

        # RSS uses <item> elements inside <channel>
        # Namespace handling: arXiv RSS uses default namespace
        ns = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
              "dc": "http://purl.org/dc/elements/1.1/",
              "": "http://purl.org/rss/1.0/"}

        # Try RDF format (arXiv uses this)
        items = root.findall(".//{http://purl.org/rss/1.0/}item")
        if not items:
            # Fallback to standard RSS 2.0
            items = root.findall(".//item")

        for item in items:
            paper = self._parse_item(item, since, category)
            if paper:
                results.append(paper)

        return results

    def _parse_item(self, item: ET.Element, since: datetime, category: str) -> Optional[dict]:
        """Parse a single RSS item into a normalized paper dict."""
        # Try multiple namespace patterns
        title = self._get_text(item, "{http://purl.org/rss/1.0/}title") or self._get_text(item, "title") or ""
        link = self._get_text(item, "{http://purl.org/rss/1.0/}link") or self._get_text(item, "link") or item.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", "")
        description = self._get_text(item, "{http://purl.org/rss/1.0/}description") or self._get_text(item, "description") or ""
        date_str = self._get_text(item, "{http://purl.org/dc/elements/1.1/}date") or self._get_text(item, "pubDate") or ""

        if not title or not link:
            return None

        # Clean up title (remove "arXiv:XXXX.XXXXX" prefix if present)
        if ". (arXiv:" in title:
            title = title.split(". (arXiv:")[0]

        # Extract arXiv ID from link
        arxiv_id = link
        if "/abs/" in link:
            arxiv_id = link.split("/abs/")[-1]

        # Parse date — RSS feeds show today's papers, so use current date if no date field
        published_dt = datetime.now(timezone.utc)
        if date_str:
            try:
                published_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # arXiv RSS shows today's submissions — they're always "since" today
        # Skip date filter for RSS (all items are fresh by definition)

        # Clean description (remove HTML tags)
        abstract = description.replace("<p>", "").replace("</p>", "").replace("<br/>", " ").strip()
        # Remove "arXiv:XXXX.XXXXX" suffixes
        if "arXiv:" in abstract:
            parts = abstract.split("arXiv:")
            abstract = parts[0].strip()

        return {
            "id": arxiv_id,
            "title": title.strip(),
            "abstract": abstract[:2000],
            "authors": [],
            "url": link if link.startswith("http") else f"http://arxiv.org/abs/{arxiv_id}",
            "source": self.name,
            "published_at": published_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "categories": [category],
        }

    def _get_text(self, element: ET.Element, tag: str) -> Optional[str]:
        """Get text content of a child element."""
        child = element.find(tag)
        return child.text.strip() if child is not None and child.text else None

    def fetch_full_text(self, paper_id: str) -> Optional[str]:
        """Fetch full text via arXiv PDF (delegates to arxiv source logic)."""
        from backend.sources.arxiv import ArxivSource
        return ArxivSource().fetch_full_text(paper_id)

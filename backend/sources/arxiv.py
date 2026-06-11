"""arXiv paper source — discovery via arXiv Atom API and full-text via PDF extraction.

Uses the arXiv API directly with requests + xml.etree (stdlib) — no lxml dependency.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import requests

from backend.shared.models import Area

logger = logging.getLogger(__name__)

_ARXIV_DELAY_S = 3.0
_ARXIV_API_URL = "http://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def _build_query(areas: list[Area]) -> str:
    """Build an arXiv search query using LLM-generated terms."""
    from backend.shared.query_gen import generate_all_queries

    queries = generate_all_queries(areas)
    if not queries:
        return ""

    return " OR ".join(f'all:"{q}"' for q in queries)


class ArxivSource:
    """Discovers papers from arXiv and fetches full text via PDF extraction."""

    name = "arxiv"

    def __init__(self, max_results_per_query: int = 50):
        self._max_results = max_results_per_query

    def discover(self, areas: list[Area], since: datetime) -> list[dict]:
        """Query arXiv for papers matching areas published since `since`."""
        query = _build_query(areas)
        if not query:
            logger.warning("ArxivSource.discover: empty query from areas")
            return []

        logger.info("ArxivSource query: %s", query)

        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        time.sleep(_ARXIV_DELAY_S)

        params = {
            "search_query": query,
            "start": 0,
            "max_results": self._max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        try:
            resp = requests.get(_ARXIV_API_URL, params=params, timeout=60)
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("ArxivSource.discover: API request failed")
            return []

        return self._parse_atom_response(resp.text, since)

    def _parse_atom_response(self, xml_text: str, since: datetime) -> list[dict]:
        """Parse the Atom XML response from arXiv API."""
        results: list[dict] = []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.exception("ArxivSource: failed to parse XML response")
            return []

        for entry in root.findall(f"{_ATOM_NS}entry"):
            try:
                published_str = entry.findtext(f"{_ATOM_NS}published", "")
                if not published_str:
                    continue

                published_dt = datetime.fromisoformat(
                    published_str.replace("Z", "+00:00")
                )
                if published_dt < since:
                    break

                entry_id = entry.findtext(f"{_ATOM_NS}id", "")
                title = entry.findtext(f"{_ATOM_NS}title", "").strip().replace("\n", " ")
                abstract = entry.findtext(f"{_ATOM_NS}summary", "").strip().replace("\n", " ")

                authors = []
                for author_el in entry.findall(f"{_ATOM_NS}author"):
                    name = author_el.findtext(f"{_ATOM_NS}name", "")
                    if name:
                        authors.append(name)

                categories = []
                for cat_el in entry.findall(f"{_ARXIV_NS}primary_category"):
                    term = cat_el.get("term", "")
                    if term:
                        categories.append(term)
                for cat_el in entry.findall(f"{_ATOM_NS}category"):
                    term = cat_el.get("term", "")
                    if term and term not in categories:
                        categories.append(term)

                results.append({
                    "id": entry_id,
                    "source": "arxiv",
                    "title": title,
                    "authors": authors,
                    "abstract": abstract,
                    "url": entry_id,
                    "published": published_dt.isoformat(),
                    "arxiv_categories": categories,
                })

            except Exception:
                logger.exception("ArxivSource: failed to parse entry")
                continue

        logger.info("ArxivSource.discover found %d papers", len(results))
        return results

    def fetch_full_text(self, paper_id: str) -> Optional[str]:
        """Download the PDF for an arXiv paper and extract text."""
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
        if paper_id.startswith("http"):
            url = paper_id.replace("/abs/", "/pdf/")
            if not url.endswith(".pdf"):
                url += ".pdf"
            return url
        return f"https://arxiv.org/pdf/{paper_id}.pdf"

    def _download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF from the given URL with rate-limit courtesy."""
        logger.info("Downloading PDF: %s", url)
        time.sleep(_ARXIV_DELAY_S)

        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()

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

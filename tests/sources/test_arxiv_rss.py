"""Tests for the arXiv RSS feed source."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
import requests as req_lib

from backend.sources.arxiv_rss import ArxivRssSource

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>cs.AI updates on arXiv.org</title>
</channel>
<item rdf:about="http://arxiv.org/abs/2606.12345">
<title>Memory-Augmented Agents for Long-Horizon Tasks. (arXiv:2606.12345v1 [cs.AI])</title>
<link>http://arxiv.org/abs/2606.12345</link>
<description>We present a memory-augmented agent architecture that enables long-horizon task completion.</description>
<dc:date>2026-06-20T00:00:00Z</dc:date>
</item>
<item rdf:about="http://arxiv.org/abs/2606.12346">
<title>Adversarial Robustness in Multi-Agent Systems. (arXiv:2606.12346v1 [cs.AI])</title>
<link>http://arxiv.org/abs/2606.12346</link>
<description>We study adversarial attacks on multi-agent systems and propose defense mechanisms.</description>
<dc:date>2026-06-20T00:00:00Z</dc:date>
</item>
</rdf:RDF>"""


class TestArxivRssSource:
    def test_discover_returns_papers(self):
        source = ArxivRssSource(categories=["cs.AI"])
        since = datetime.now(timezone.utc) - timedelta(days=7)

        with patch("backend.sources.arxiv_rss.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = SAMPLE_RSS
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since)

        assert len(papers) == 2
        assert papers[0]["title"] == "Memory-Augmented Agents for Long-Horizon Tasks"
        assert papers[0]["source"] == "arxiv_rss"
        assert papers[0]["id"] == "2606.12345"

    def test_discover_deduplicates_across_categories(self):
        source = ArxivRssSource(categories=["cs.AI", "cs.CL"])
        since = datetime.now(timezone.utc) - timedelta(days=7)

        with patch("backend.sources.arxiv_rss.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = SAMPLE_RSS
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since)

        # Same RSS returned for both categories, but deduped by ID
        assert len(papers) == 2

    def test_discover_handles_api_failure(self):
        source = ArxivRssSource(categories=["cs.AI"])
        since = datetime.now(timezone.utc) - timedelta(days=7)

        with patch("backend.sources.arxiv_rss.requests.get") as mock_get:
            mock_get.side_effect = Exception("Network error")
            papers = source.discover([], since)

        assert papers == []

    def test_parses_arxiv_id_from_link(self):
        source = ArxivRssSource(categories=["cs.AI"])
        since = datetime.now(timezone.utc) - timedelta(days=7)

        with patch("backend.sources.arxiv_rss.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = SAMPLE_RSS
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since)

        assert papers[0]["id"] == "2606.12345"
        assert papers[1]["id"] == "2606.12346"

    def test_strips_arxiv_suffix_from_title(self):
        source = ArxivRssSource(categories=["cs.AI"])
        since = datetime.now(timezone.utc) - timedelta(days=7)

        with patch("backend.sources.arxiv_rss.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = SAMPLE_RSS
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since)

        # Title should NOT contain the "(arXiv:...)" suffix
        assert "arXiv:" not in papers[0]["title"]

    def test_empty_rss_returns_empty(self):
        empty_rss = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/">
<channel><title>cs.AI</title></channel>
</rdf:RDF>"""

        source = ArxivRssSource(categories=["cs.AI"])
        since = datetime.now(timezone.utc) - timedelta(days=7)

        with patch("backend.sources.arxiv_rss.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = empty_rss
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            papers = source.discover([], since)

        assert papers == []

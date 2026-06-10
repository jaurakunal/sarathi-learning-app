"""arXiv paper source."""

from __future__ import annotations

from datetime import datetime

from backend.shared.models import Area


class ArxivSource:
    name = "arxiv"

    def discover(self, areas: list[Area], since: datetime) -> list[dict]:
        raise NotImplementedError("arXiv discovery — M0 build step")

    def fetch_full_text(self, paper_id: str) -> str | None:
        raise NotImplementedError("arXiv full text fetch — M0 build step")

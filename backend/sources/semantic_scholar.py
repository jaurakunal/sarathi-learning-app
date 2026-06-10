"""Semantic Scholar paper source."""

from __future__ import annotations

from datetime import datetime

from backend.shared.models import Area


class SemanticScholarSource:
    name = "semantic_scholar"

    def discover(self, areas: list[Area], since: datetime) -> list[dict]:
        raise NotImplementedError("Semantic Scholar discovery — M0 build step")

    def fetch_full_text(self, paper_id: str) -> str | None:
        raise NotImplementedError("Semantic Scholar full text — M0 build step")

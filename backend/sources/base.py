"""Paper source interface. Each source implements this protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from backend.shared.models import Area


@runtime_checkable
class PaperSource(Protocol):
    name: str

    def discover(self, areas: list[Area], since: datetime, queries: list[str] | None = None) -> list[dict]:
        """Query the source for papers matching the given areas since a date.

        Args:
            areas: User's research areas (for context/fallback).
            since: Only return papers published after this date.
            queries: Pre-generated search queries (from LLM). If provided,
                     sources should use these directly instead of building
                     their own queries from areas.

        Returns a list of raw paper dicts normalized to:
        {id, source, title, authors, abstract, url, published, ...optional source-specific fields}
        """
        ...

    def fetch_full_text(self, paper_id: str) -> str | None:
        """Fetch the full text of a paper. Returns None if unavailable."""
        ...

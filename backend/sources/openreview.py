"""OpenReview paper source."""

from __future__ import annotations

from datetime import datetime

from backend.shared.models import Area


class OpenReviewSource:
    name = "openreview"

    def discover(self, areas: list[Area], since: datetime) -> list[dict]:
        raise NotImplementedError("OpenReview discovery — M0 build step")

    def fetch_full_text(self, paper_id: str) -> str | None:
        raise NotImplementedError("OpenReview full text — M0 build step")

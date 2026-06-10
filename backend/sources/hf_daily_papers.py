"""Hugging Face Daily Papers source."""

from __future__ import annotations

from datetime import datetime

from backend.shared.models import Area


class HFDailyPapersSource:
    name = "hf_daily_papers"

    def discover(self, areas: list[Area], since: datetime) -> list[dict]:
        raise NotImplementedError("HF Daily Papers discovery — M0 build step")

    def fetch_full_text(self, paper_id: str) -> str | None:
        raise NotImplementedError("HF Daily Papers full text — M0 build step")

"""Batch LLM relevance filter — coarse "is this in my ballpark?" check.

Used by the Discover step to filter raw source results before writing
candidates to DDB. This is NOT triage — it only asks "does this paper
relate to any of my research areas?" (binary, batch, coarse).

Triage then does the nuanced per-paper scoring: level, hypothesis fit,
worth-my-hours.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from backend.shared.llm import call_llm
from backend.shared.models import Area

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a relevance filter for a research paper discovery system.

Given a list of research areas and a batch of paper titles+abstracts, identify which papers are relevant to ANY of the research areas.

A paper is relevant if it directly relates to, could inform, or intersects with at least one of the research areas. Be INCLUSIVE — when in doubt, include it. The next step (triage) will do fine-grained scoring. Your job is only to remove clearly irrelevant papers (e.g., a pure biology paper when the areas are all about AI agents).

Return a JSON array of the INDICES (0-based) of relevant papers. Only exclude papers that are clearly outside all research areas."""


def batch_relevance_filter(
    papers: list[dict],
    areas: list[Area],
    model_id: Optional[str] = None,
) -> list[dict]:
    """Filter a batch of papers for relevance to the user's research areas.

    Uses one LLM call to assess all papers at once. Returns only the papers
    the LLM identifies as relevant. Falls back to returning all papers if
    the LLM call fails (fail-open: better to let irrelevant papers through
    to triage than to drop relevant ones).

    Args:
        papers: List of paper dicts (must have 'title' and 'abstract').
        areas: User's research areas.
        model_id: Optional Bedrock model override.

    Returns:
        Filtered list of papers (subset of input).
    """
    if not papers:
        return []

    if len(papers) <= 3:
        return papers

    # Batch large sets to avoid exceeding context/output limits
    if len(papers) > 25:
        mid = len(papers) // 2
        first_half = batch_relevance_filter(papers[:mid], areas, model_id)
        second_half = batch_relevance_filter(papers[mid:], areas, model_id)
        return first_half + second_half

    areas_desc = "\n".join(
        f"- {a.label}: {', '.join(a.just_right[:3])}" for a in areas
    )

    paper_list = "\n".join(
        f"[{i}] {p.get('title', 'Untitled')}\n    {p.get('abstract', '')[:200]}"
        for i, p in enumerate(papers)
    )

    user_message = f"""Research areas:
{areas_desc}

Papers to evaluate ({len(papers)} total):
{paper_list}

Return a JSON array of indices (0-based) for papers relevant to ANY of the research areas above. Be inclusive — only exclude clearly irrelevant papers."""

    kwargs = {"system": SYSTEM_PROMPT, "user_message": user_message, "max_tokens": 1000}
    if model_id:
        kwargs["model_id"] = model_id

    response = call_llm(**kwargs)

    if not response:
        logger.warning("Relevance filter LLM call failed — returning all papers (fail-open)")
        return papers

    try:
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        indices = json.loads(text)
        if not isinstance(indices, list):
            raise ValueError(f"Expected list, got {type(indices)}")

        valid_indices = [i for i in indices if isinstance(i, int) and 0 <= i < len(papers)]
        filtered = [papers[i] for i in valid_indices]

        logger.info(
            "Relevance filter: %d/%d papers passed (%d filtered out)",
            len(filtered), len(papers), len(papers) - len(filtered),
        )
        return filtered

    except (json.JSONDecodeError, ValueError, IndexError) as e:
        logger.warning("Relevance filter parse failed (%s) — returning all papers (fail-open)", e)
        return papers

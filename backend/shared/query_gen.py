"""LLM-powered search query generation from user profile areas."""

from __future__ import annotations

import json
import logging
from typing import Optional

from backend.shared.llm import call_llm
from backend.shared.models import Area

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You generate academic paper search queries for arXiv and similar academic search engines.

Given a research area description, generate 3-5 diverse search queries that would find relevant papers. Each query should:
- Use terms that actual researchers use in paper titles and abstracts
- Be specific enough to return relevant results but broad enough to find papers (avoid AND-ing too many terms)
- Cover different angles of the area (theoretical, applied, specific techniques, related subfields)
- Use standard academic terminology, not conversational descriptions

Return a JSON array of query strings. Each query should be 2-4 words max — these are keyword searches, not sentences.

Example:
Area: "Long-running autonomous agents that can manage online stores"
Output: ["autonomous agent planning", "LLM agent long-horizon tasks", "web agent e-commerce", "persistent agent architecture", "multi-step agent execution"]
"""


def generate_queries_for_area(area: Area, model_id: Optional[str] = None) -> list[str]:
    """Use an LLM to generate 3-5 search queries for a given research area.

    Falls back to basic keyword extraction if LLM call fails.
    """
    user_message = f"""Generate search queries for this research area:

Label: {area.label}
Key topics I'm interested in: {', '.join(area.just_right)}
Current frontier: {area.frontier}

Return a JSON array of 3-5 search query strings."""

    kwargs = {"system": SYSTEM_PROMPT, "user_message": user_message, "max_tokens": 300}
    if model_id:
        kwargs["model_id"] = model_id

    response = call_llm(**kwargs)

    if response:
        try:
            # Handle markdown-fenced JSON
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            queries = json.loads(text)
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                logger.info("Generated %d queries for area '%s': %s", len(queries), area.label, queries)
                return queries
        except (json.JSONDecodeError, IndexError):
            logger.warning("Failed to parse LLM query response for area '%s': %s", area.label, response[:200])

    # Fallback: use just_right keywords as individual queries
    fallback = area.just_right[:5] if area.just_right else [area.label]
    logger.info("Using fallback queries for area '%s': %s", area.label, fallback)
    return fallback


def generate_all_queries(areas: list[Area], model_id: Optional[str] = None) -> list[str]:
    """Generate search queries for all areas, deduplicated."""
    all_queries: list[str] = []
    seen: set[str] = set()

    for area in areas:
        queries = generate_queries_for_area(area, model_id)
        for q in queries:
            q_lower = q.lower().strip()
            if q_lower not in seen:
                seen.add(q_lower)
                all_queries.append(q)

    logger.info("Total unique queries generated: %d", len(all_queries))
    return all_queries

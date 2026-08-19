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

Tailor the queries to the user's INTENT and LEVEL for this area — this is what determines whether the candidate pool contains the RIGHT KIND of paper (a ranker downstream can only pick from what these queries find):
- intent=consume (they want to learn/understand): bias toward foundational, well-established, and pedagogical work. Include terms like "survey", "review", "tutorial", "overview", and the canonical named methods/benchmarks of the area.
- intent=produce (they want to build/publish): bias toward the frontier — novel methods, state-of-the-art, and implementable/reproducible work. Favor recent terminology and specific new method names over broad overviews.
- intent=both: mix the two.
- level=beginner: prefer the area's foundational vocabulary; avoid hyper-specialized jargon.
- level=advanced: use precise, specialized terminology and edge subfields; skip the introductory terms.

Return a JSON array of query strings. Each query should be 2-4 words max — these are keyword searches, not sentences.

Example (intent=consume, level=beginner):
Area: "Long-running autonomous agents that can manage online stores"
Output: ["autonomous agent survey", "LLM agent overview", "web agent tutorial", "agent planning review", "multi-step agent introduction"]

Example (intent=produce, level=advanced):
Area: "Long-running autonomous agents that can manage online stores"
Output: ["long-horizon agent memory", "novel web agent architecture", "agent self-refinement SOTA", "persistent agent state", "multi-agent e-commerce execution"]
"""


def generate_queries_for_area(area: Area, model_id: Optional[str] = None) -> list[str]:
    """Use an LLM to generate 3-5 search queries for a given research area.

    Falls back to basic keyword extraction if LLM call fails.
    Uses the current date as a variation seed so each run produces slightly
    different queries, discovering papers from new angles.
    """
    from datetime import datetime, timezone
    date_seed = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    intent = getattr(area, "intent", "consume") or "consume"
    level = getattr(area, "current_level", "intermediate") or "intermediate"
    user_message = f"""Generate search queries for this research area:

Label: {area.label}
Key topics I'm interested in: {', '.join(area.just_right)}
Current frontier: {area.frontier}
Intent: {intent}   (consume = learn/understand; produce = build/publish)
Level: {level}

Today's date: {date_seed} (use this to vary your query angles from previous runs — explore different facets, adjacent topics, or newer terminology each time)

Return a JSON array of 3-5 search query strings tailored to the Intent and Level above."""

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

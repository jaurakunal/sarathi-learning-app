"""Section-based chunking with contextual retrieval for research papers.

Uses LLM to segment papers into labeled sections, then prepends context
to each section so chunks are self-contained for embedding.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from backend.shared.llm import call_llm

logger = logging.getLogger(__name__)

SECTION_SYSTEM_PROMPT = """You segment research papers into their major sections.

Given a paper's full text, identify the sections and return a JSON array.
Each section has a "name" (short label like "abstract", "introduction", "method", "results", "discussion", "related_work", "conclusion") and "text" (the full content of that section).

Rules:
- Use lowercase section names
- If the paper doesn't have clear sections (e.g., a blog post), segment by topic/theme
- Combine very short sections (< 100 words) with adjacent ones
- Each section should be 200-3000 words ideally
- Return valid JSON only — no markdown fences, no explanation

Example output:
[{"name": "abstract", "text": "..."}, {"name": "introduction", "text": "..."}, ...]"""

FALLBACK_CHUNK_SIZE = 4000  # chars (~1000 tokens) for fallback chunking


def chunk_paper_into_sections(
    full_text: str,
    paper_title: str,
    paper_id: str,
    model_id: Optional[str] = None,
    use_llm: bool = True,
) -> list[dict]:
    """Segment a paper into sections and prepend context for embedding.

    Args:
        full_text: The paper's full text.
        paper_title: Title of the paper.
        paper_id: Unique paper identifier.
        model_id: Optional LLM model override.
        use_llm: If False, skip LLM and use regex/fallback only (faster for backfill).

    Returns:
        List of dicts: [{chunk_text, section_name, paper_id, paper_title}]
        chunk_text includes the prepended context.
    """
    sections = None

    # Try regex-based section detection first (fast, no LLM cost)
    sections = _segment_with_regex(full_text)

    # If regex didn't find clear sections and LLM is enabled, try LLM
    if not sections and use_llm:
        sections = _segment_with_llm(full_text, model_id)

    if not sections:
        # Final fallback: chunk by paragraph boundaries
        logger.warning("Section detection failed for %s — using fallback chunking", paper_id)
        sections = _fallback_chunk(full_text)

    # Prepend context to each section (Anthropic's Contextual Retrieval approach)
    chunks = []
    for section in sections:
        section_name = section.get("name", "section")
        section_text = section.get("text", "")

        if not section_text or len(section_text.strip()) < 50:
            continue

        # Context prefix makes the chunk self-contained for embedding
        context_prefix = (
            f"This is the {section_name} section of the paper \"{paper_title}\" "
            f"(paper_id: {paper_id}). "
        )

        chunks.append({
            "chunk_text": context_prefix + section_text,
            "section_name": section_name,
            "paper_id": paper_id,
            "paper_title": paper_title,
        })

    logger.info("Chunked paper %s into %d sections", paper_id, len(chunks))
    return chunks


import re

# Common section headings in research papers
_SECTION_PATTERNS = [
    r"^#{1,3}\s+(.+)$",           # Markdown headings
    r"^(\d+\.?\s+[A-Z].+)$",      # "1. Introduction", "2 Method"
    r"^([A-Z][A-Za-z\s]{3,30})$",  # ALL CAPS or Title Case standalone lines (e.g., "Abstract", "Introduction")
]


def _segment_with_regex(full_text: str) -> list[dict]:
    """Try to detect section boundaries using common heading patterns."""
    lines = full_text.split("\n")
    sections = []
    current_name = "abstract"
    current_lines: list[str] = []

    heading_pattern = re.compile(
        r"^(?:#{1,3}\s+(.+)|(\d+\.?\s*[A-Z][A-Za-z\s:]+)|([A-Z][A-Z\s]{3,30}))$"
    )

    for line in lines:
        match = heading_pattern.match(line.strip())
        if match and len(line.strip()) < 60:
            # Save previous section
            if current_lines:
                text = "\n".join(current_lines).strip()
                if len(text) > 100:
                    sections.append({"name": current_name.lower().strip(), "text": text})
            # Start new section
            heading = match.group(1) or match.group(2) or match.group(3)
            current_name = heading.strip().lower().rstrip(".")
            # Normalize common variations
            for pattern, normalized in [
                ("intro", "introduction"), ("method", "method"), ("result", "results"),
                ("discuss", "discussion"), ("conclu", "conclusion"), ("related", "related_work"),
                ("abstract", "abstract"), ("experiment", "experiments"),
            ]:
                if pattern in current_name:
                    current_name = normalized
                    break
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last section
    if current_lines:
        text = "\n".join(current_lines).strip()
        if len(text) > 100:
            sections.append({"name": current_name.lower().strip(), "text": text})

    # Only use regex result if we found at least 3 sections (indicates real structure)
    if len(sections) >= 3:
        logger.info("Regex segmentation found %d sections", len(sections))
        return sections

    return []


def _segment_with_llm(full_text: str, model_id: Optional[str] = None) -> list[dict]:
    """Use LLM to segment text into sections."""
    # Truncate for the LLM call (context window limit)
    truncated = full_text[:100000]

    user_message = f"Segment this paper into sections:\n\n{truncated}"

    kwargs = {
        "system": SECTION_SYSTEM_PROMPT,
        "user_message": user_message,
        "max_tokens": 8192,
        "temperature": 0.1,
    }
    if model_id:
        kwargs["model_id"] = model_id

    response = call_llm(**kwargs)
    if not response:
        return []

    # Parse JSON response
    try:
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        sections = json.loads(text)
        if isinstance(sections, list):
            return sections
    except (json.JSONDecodeError, IndexError):
        logger.warning("Failed to parse LLM section segmentation response")

    return []


def _fallback_chunk(full_text: str) -> list[dict]:
    """Fallback: split by paragraph boundaries with target size."""
    paragraphs = full_text.split("\n\n")
    chunks = []
    current_chunk = ""
    chunk_idx = 0

    for para in paragraphs:
        if len(current_chunk) + len(para) > FALLBACK_CHUNK_SIZE and current_chunk:
            chunks.append({"name": f"section_{chunk_idx}", "text": current_chunk.strip()})
            chunk_idx += 1
            current_chunk = para
        else:
            current_chunk += "\n\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append({"name": f"section_{chunk_idx}", "text": current_chunk.strip()})

    return chunks

"""Pipeline step: Generate hook + multi-level digest for selected papers.

This runs as a Fargate task (not Lambda) because it's LLM-heavy and may
exceed the 15-minute Lambda timeout for multiple papers.

Entrypoint: run(event) called from __main__.
Event: {user_id, table_name, s3_bucket, model (optional)}
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import boto3

from backend.shared import db
from backend.shared.llm import call_llm, call_llm_with_fallback
from backend.sources.arxiv import ArxivSource
from backend.sources.arxiv_rss import ArxivRssSource
from backend.sources.hf_daily_papers import HFDailyPapersSource
from backend.sources.openreview import OpenReviewSource
from backend.sources.papers_with_code import PapersWithCodeSource
from backend.sources.semantic_scholar import SemanticScholarSource

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Source registry — maps paper.source field to a source instance
# ---------------------------------------------------------------------------


def _get_s2_api_key() -> Optional[str]:
    """Read S2 API key from SSM (cached after first call)."""
    param_name = os.environ.get("S2_API_KEY_PARAM", "/sarathi/semantic-scholar-api-key")
    try:
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception:
        logger.warning("Could not read S2 API key from SSM — using unauthenticated")
        return None


def _build_sources() -> dict:
    """Build source instances (deferred so API key can be loaded at runtime)."""
    api_key = _get_s2_api_key()
    return {
        "arxiv": ArxivSource(),
        "arxiv_rss": ArxivRssSource(),
        "semantic_scholar": SemanticScholarSource(api_key=api_key),
        "openreview": OpenReviewSource(),
        "hf_daily_papers": HFDailyPapersSource(),
        "papers_with_code": PapersWithCodeSource(),
    }

DEFAULT_MODEL = os.environ.get("DIGEST_MODEL", "moonshotai.kimi-k2.5")
FALLBACK_MODEL = "us.anthropic.claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_card_id(paper_id: str) -> str:
    """Generate a card_id with timestamp prefix for sort ordering.

    Format: YYYYMMDD_HHMMSS_<short_hash>
    The timestamp prefix ensures feed cards sort newest-first in DDB.
    """
    now = datetime.now(timezone.utc)
    ts_prefix = now.strftime("%Y%m%d_%H%M%S")
    short_hash = hashlib.sha256(
        f"{paper_id}:{now.isoformat()}".encode()
    ).hexdigest()[:8]
    return f"{ts_prefix}_{short_hash}"


def _build_profile_context(profile: dict) -> str:
    """Serialize the user profile into a compact string for the LLM prompt."""
    parts: list[str] = []

    # Meta / learning style
    meta = profile.get("meta") or {}
    learning_style = meta.get("learning_style", {})
    if learning_style:
        parts.append("LEARNING STYLE:")
        for k, v in learning_style.items():
            parts.append(f"  {k}: {v}")

    paper_goal = meta.get("paper_goal", "")
    if paper_goal:
        parts.append(f"\nPAPER GOAL: {paper_goal}")

    # Areas
    areas = profile.get("areas") or []
    if areas:
        parts.append("\nRESEARCH AREAS:")
        for area in areas:
            role = area.get("role", "secondary")
            status = area.get("status", "active")
            label = area.get("label", area.get("id", ""))
            frontier = area.get("frontier", "")
            just_right = area.get("just_right", [])
            too_basic = area.get("too_basic", [])

            parts.append(f"  [{role}/{status}] {label}")
            if frontier:
                parts.append(f"    Frontier: {frontier}")
            if just_right:
                parts.append(f"    Calibrated terms: {', '.join(just_right)}")
            if too_basic:
                parts.append(f"    Too basic: {', '.join(too_basic)}")

    # Hypothesis
    hypothesis = profile.get("hypothesis") or {}
    if hypothesis:
        stmt = hypothesis.get("statement", "")
        if stmt:
            parts.append(f"\nHYPOTHESIS: {stmt}")
        status = hypothesis.get("status", "")
        if status:
            parts.append(f"  Status: {status}")
        supporting = hypothesis.get("supporting", [])
        if supporting:
            notes = [s.get("note", "") for s in supporting if s.get("note")]
            if notes:
                parts.append(f"  Supporting evidence: {'; '.join(notes)}")

    # Summaries (most recent context)
    summaries = profile.get("summaries") or []
    if summaries:
        parts.append("\nRECENT SUMMARIES:")
        # Sort by tier weight for context relevance
        tier_order = {"yesterday": 0, "3_day": 1, "7_day": 2, "month": 3, "quarter": 4}
        summaries_sorted = sorted(
            summaries, key=lambda s: tier_order.get(s.get("tier", ""), 99)
        )
        for s in summaries_sorted[:3]:  # Top 3 most recent tiers
            tier = s.get("tier", "")
            content = s.get("content", "")
            if content:
                parts.append(f"  [{tier}] {content[:500]}")

    return "\n".join(parts)


def _build_system_prompt(profile_context: str) -> str:
    """Build the system prompt for feed card generation."""
    return f"""You are generating a feed card for Sarathi, a personal research tool. The user is a practitioner who builds things but hasn't read papers. They route around math — they want the intuition first, equation only as an optional reveal.

USER PROFILE:
{profile_context}

YOUR JOB: Generate a feed card that earns the next 5 seconds of attention. Then the next 30. Then the next 5 minutes.

RULES:
- The hook must create an ITCH — a question the user now needs answered — NOT a dry summary. It's a provocation anchored to what they've built and what they care about.
- Lead with the applied angle. "What can I build with this?" always beats "What did the authors prove?"
- Never flatter. Never oversell. If the paper is mediocre, say so in honesty_note.
- Glossary entries should be at THIS user's level — skip terms they already know (check too_basic), define terms at their frontier.
- Math notes: intuition FIRST. The equation is a tap-to-reveal optional extra, never the lead.
- Be honest about paper quality. A "just skim the abstract" honesty_note is fine if that's the truth.
- why_you_now must be specific — what in their current work/thesis/frontier makes THIS paper timely.
- suggested_questions should be things this specific user would actually ask, given their projects and level.

Respond with ONLY a JSON object (no markdown, no explanation) with these exact keys:
- hook (string): 1-2 sentence provocation. Earn the next 5 seconds. NOT a summary.
- why_you_now (string): Why this paper matters to THIS user right NOW.
- time_estimate (string): Estimated reading time for the digest (e.g., "12 min").
- digest (object):
  - gist (string): 1 paragraph plain-language summary. No jargon without defining it.
  - key_ideas (array of strings): 3-5 bullet points, each one sentence.
  - deep (string): 2-4 paragraph deep-dive. Technical but accessible at their level.
- glossary (array of objects): Each has "term" (string) and "plain" (string). Only include terms at their frontier — skip what's too basic for them.
- math_notes (array of objects): Each has "plain" (string, the intuition) and "equation_optional" (string, the formal notation). Only include if there's actual math worth noting.
- hypothesis_relevance (string): How this paper relates to their thesis. Supports/refutes/refines?
- honesty_note (string): Honest assessment — full read, skim, or skip-after-digest? Why?
- suggested_questions (array of strings): 3-5 questions this user would want to ask about this paper."""


def _build_user_prompt(paper: dict, full_text: str) -> str:
    """Build the user prompt with paper metadata and full text."""
    # Truncate full text if extremely long to stay within context window
    # Claude supports large contexts but we want to be cost-conscious
    max_text_chars = 150_000  # ~37K tokens, plenty for most papers
    text_for_prompt = full_text[:max_text_chars]
    if len(full_text) > max_text_chars:
        text_for_prompt += "\n\n[... text truncated for length ...]"

    return f"""PAPER METADATA:
Title: {paper.get('title', 'Unknown')}
Authors: {', '.join(paper.get('authors', []))}
Source: {paper.get('source', 'unknown')}
Published: {paper.get('published', 'unknown')}
URL: {paper.get('url', '')}
Areas matched: {', '.join(paper.get('areas_matched', []))}
Triage reasoning: {paper.get('triage_reasoning', '')}

FULL TEXT:
{text_for_prompt}"""


def _generate_card(
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> Optional[dict]:
    """Call the LLM to generate the feed card content. Returns parsed JSON or None.

    Uses Kimi K2.5 (or whatever DIGEST_MODEL is set to) as the primary model and
    falls back to Sonnet on failure.
    """
    try:
        text = call_llm_with_fallback(
            system=system_prompt,
            user_message=user_prompt,
            primary_model=model,
            fallback_model=FALLBACK_MODEL,
            max_tokens=8192,
        )

        if text is None:
            logger.error("LLM call returned None")
            return None

        # Parse JSON — the model should return raw JSON per the system prompt
        # Strip any markdown code fences if the model wraps it
        text = text.strip()
        if text.startswith("```"):
            # Remove opening fence (possibly with language hint)
            first_newline = text.index("\n")
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        return json.loads(text)

    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error calling LLM: %s", e)
        return None


def _upload_full_text(
    s3_client: Any, bucket: str, user_id: str, paper_id: str, full_text: str
) -> str:
    """Upload full text to S3 and return the key."""
    key = f"users/{user_id}/papers/{paper_id}/full_text.txt"
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=full_text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    logger.info("Uploaded full text to s3://%s/%s", bucket, key)
    return key


# ---------------------------------------------------------------------------
# Main pipeline step
# ---------------------------------------------------------------------------


def run(event: dict) -> dict:
    """Fargate entrypoint for the Digest step.

    For each surfaced paper:
    1. Fetch full text from source
    2. Store full text in S3
    3. Generate: hook, why_you_now, digest (gist + key_ideas + deep),
       glossary, math_notes, hypothesis_relevance, honesty_note,
       suggested_questions
    4. Write feed_card to DDB

    Returns: {"cards_generated": N, "papers_failed": M}
    """
    user_id = event["user_id"]
    table_name = event["table_name"]
    s3_bucket = event["s3_bucket"]
    model = event.get("model", DEFAULT_MODEL)

    logger.info(
        "Digest step starting: user=%s, table=%s, bucket=%s, model=%s",
        user_id, table_name, s3_bucket, model,
    )

    # Initialize clients
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)
    s3_client = boto3.client("s3")

    # 1. Read the user's full profile
    profile = db.get_full_profile(table, user_id)
    if not profile.get("meta"):
        logger.error("No profile found for user %s — cannot generate digests", user_id)
        return {"cards_generated": 0, "papers_failed": 0, "error": "no_profile"}

    profile_context = _build_profile_context(profile)
    system_prompt = _build_system_prompt(profile_context)

    # 2. Read all papers with status="surfaced"
    surfaced_papers = db.list_papers_by_status(table, user_id, "surfaced", limit=50)
    logger.info("Found %d surfaced papers to digest", len(surfaced_papers))

    if not surfaced_papers:
        return {"cards_generated": 0, "papers_failed": 0}

    sources = _build_sources()
    cards_generated = 0
    papers_failed = 0

    # 3. Process each surfaced paper
    for paper in surfaced_papers:
        paper_id = paper.get("id", "")
        source_name = paper.get("source", "")
        title = paper.get("title", "Unknown")

        logger.info("Processing paper: %s [%s] from %s", paper_id, title, source_name)

        try:
            # 3a. Fetch full text using the appropriate source
            source = sources.get(source_name)
            if source is None:
                logger.warning(
                    "Unknown source '%s' for paper %s — skipping",
                    source_name, paper_id,
                )
                papers_failed += 1
                continue

            full_text = source.fetch_full_text(paper_id)
            if not full_text:
                logger.warning(
                    "Could not fetch full text for paper %s — skipping", paper_id
                )
                papers_failed += 1
                continue

            # 3b. Store full text in S3
            s3_key = _upload_full_text(s3_client, s3_bucket, user_id, paper_id, full_text)

            # 3b-ii. Chunk + embed for RAG (skip if already embedded globally)
            if not db.is_paper_embedded(table, paper_id):
                try:
                    from backend.shared.chunker import chunk_paper_into_sections
                    from backend.shared.embeddings import embed_batch
                    from backend.shared.vectors import put_vectors

                    chunks = chunk_paper_into_sections(full_text, title, paper_id)
                    if chunks:
                        embeddings = embed_batch([c["chunk_text"] for c in chunks])
                        stored = put_vectors(chunks, embeddings)
                        if stored > 0:
                            db.mark_paper_embedded(table, paper_id, stored)
                            logger.info("Embedded paper %s: %d sections", paper_id, stored)
                except Exception:
                    logger.warning("Embedding failed for paper %s — continuing without RAG", paper_id)

            # 3c. Call LLM to generate feed card content
            user_prompt = _build_user_prompt(paper, full_text)
            llm_result = _generate_card(model, system_prompt, user_prompt)

            if llm_result is None:
                logger.error(
                    "LLM generation failed for paper %s — skipping", paper_id
                )
                papers_failed += 1
                continue

            # 3d. Generate card_id with timestamp prefix
            card_id = _generate_card_id(paper_id)

            # 3e. Assemble and write the feed card to DDB
            feed_card = {
                "card_id": card_id,
                "paper_id": paper_id,
                "source_url": paper.get("url", ""),
                "full_text_s3_key": s3_key,
                "card_type": "new_paper",
                "hook": llm_result.get("hook", ""),
                "why_you_now": llm_result.get("why_you_now", ""),
                "time_estimate": llm_result.get("time_estimate", ""),
                "digest": llm_result.get("digest", {}),
                "glossary": llm_result.get("glossary", []),
                "math_notes": llm_result.get("math_notes", []),
                "hypothesis_relevance": llm_result.get("hypothesis_relevance", ""),
                "honesty_note": llm_result.get("honesty_note", ""),
                "suggested_questions": llm_result.get("suggested_questions", []),
            }

            db.put_feed_card(table, user_id, feed_card)
            logger.info(
                "Feed card written: card_id=%s for paper=%s", card_id, paper_id
            )

            # Mark paper as digested so it won't be re-processed next run
            paper["status"] = "digested"
            db.put_paper(table, user_id, paper)

            cards_generated += 1

        except Exception:
            logger.exception("Unexpected error processing paper %s", paper_id)
            papers_failed += 1
            continue

    result = {"cards_generated": cards_generated, "papers_failed": papers_failed}
    logger.info("Digest step complete: %s", result)

    # Send push notification if new cards were generated
    if cards_generated > 0:
        try:
            from backend.shared.push import send_push_notification
            noun = "paper" if cards_generated == 1 else "papers"
            send_push_notification(
                table, user_id,
                title="Sārathi",
                body=f"{cards_generated} new {noun} in your feed",
                url="/",
            )
        except Exception:
            logger.warning("Push notification failed — continuing")

    return result


if __name__ == "__main__":
    import json
    import os
    import sys

    if len(sys.argv) > 1:
        event = json.loads(sys.argv[1])
    else:
        # Fargate passes config via environment variables
        event = {
            "user_id": os.environ.get("USER_ID", ""),
            "table_name": os.environ.get("TABLE_NAME", ""),
            "s3_bucket": os.environ.get("S3_BUCKET", os.environ.get("BUCKET_NAME", "")),
        }

    if not event.get("user_id") or not event.get("table_name"):
        print("ERROR: user_id and table_name required (via argv or env vars)")
        sys.exit(1)

    result = run(event)
    print(json.dumps(result))
    # Exit 1 only if papers were attempted but ALL failed.
    # Zero surfaced papers (nothing to do) = success (exit 0).
    # Partial failures (some papers skipped) = success (exit 0).
    papers_failed = result.get("papers_failed", 0)
    cards_generated = result.get("cards_generated", 0)
    if papers_failed > 0 and cards_generated == 0:
        sys.exit(1)
    else:
        sys.exit(0)

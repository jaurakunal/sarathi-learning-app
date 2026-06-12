"""Pipeline step: Discover candidate papers from all sources."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import boto3

from backend.shared import db
from backend.shared.models import Area, PaperStatus
from backend.sources.arxiv import ArxivSource
from backend.sources.hf_daily_papers import HFDailyPapersSource
from backend.sources.openreview import OpenReviewSource
from backend.sources.semantic_scholar import SemanticScholarSource

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _area_from_dict(item: dict) -> Area:
    """Convert a DDB area item dict back into an Area model object."""
    return Area(
        id=item.get("id", ""),
        user_id=item.get("user_id", ""),
        label=item.get("label", ""),
        status=item.get("status", "active"),
        role=item.get("role", "secondary"),
        links=item.get("links", []),
        frontier=item.get("frontier", ""),
        too_basic=item.get("too_basic", []),
        just_right=item.get("just_right", []),
        added_at=item.get("added_at"),
    )


def _deduplicate_by_title(papers: list[dict]) -> list[dict]:
    """Deduplicate papers by case-insensitive title, keeping the first occurrence."""
    seen_titles: set[str] = set()
    unique: list[dict] = []

    for paper in papers:
        title_key = paper.get("title", "").strip().lower()
        if not title_key:
            # Papers without titles are kept but won't dedup against anything
            unique.append(paper)
            continue
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique.append(paper)

    return unique


def _make_paper_record(paper: dict, discovered_at: str) -> dict:
    """Convert a source paper dict into the format expected by db.put_paper."""
    return {
        "id": paper.get("id", ""),
        "source": paper.get("source", ""),
        "title": paper.get("title", ""),
        "authors": paper.get("authors", []),
        "abstract": paper.get("abstract", ""),
        "url": paper.get("url", ""),
        "published": paper.get("published", ""),
        "status": PaperStatus.CANDIDATE.value,
        "triage_score": 0,
        "worth_my_hours": False,
        "discovered_at": discovered_at,
        # Preserve any extra source-specific metadata
        "arxiv_categories": paper.get("arxiv_categories", []),
        "fields_of_study": paper.get("fields_of_study", []),
        "citation_count": paper.get("citation_count", 0),
        "influential_citation_count": paper.get("influential_citation_count", 0),
        "upvotes": paper.get("upvotes", 0),
        "venue": paper.get("venue", ""),
        "peer_review_score": paper.get("peer_review_score"),
    }


def handler(event: dict, context) -> dict:
    """Lambda handler for the Discover step.

    Reads profile areas from DDB, queries all sources, writes candidate
    paper records to DDB (deduplicating against already-seen papers).

    Args:
        event: Dict with keys:
            - user_id (str): Cognito sub
            - table_name (str): DDB table name
            - since_days (int, optional): How many days back to search. Default 7.
        context: Lambda context (unused).

    Returns:
        Summary dict with candidates_found, new_candidates_written, duplicates_skipped.
    """
    user_id = event["user_id"]
    table_name = event["table_name"]
    since_days = event.get("since_days", 7)

    # Create the DDB table resource
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # Step 1: Read user's areas from DDB
    area_items = db.get_profile_areas(table, user_id)
    if not area_items:
        logger.warning("No areas found for user %s — nothing to discover", user_id)
        return {
            "candidates_found": 0,
            "new_candidates_written": 0,
            "duplicates_skipped": 0,
        }

    # Step 2: Convert area dicts to Area model objects
    areas = [_area_from_dict(item) for item in area_items]
    logger.info("Loaded %d areas for user %s", len(areas), user_id)

    # Step 3: Compute the since datetime
    since = datetime.now(timezone.utc) - timedelta(days=since_days)

    # Step 4: Generate search queries ONCE (shared across all sources)
    from backend.shared.query_gen import generate_all_queries
    queries = generate_all_queries(areas)
    logger.info("Generated %d search queries: %s", len(queries), queries)

    # Step 5: Query all sources with the pre-generated queries
    sources = [
        ArxivSource(),
        SemanticScholarSource(),
        HFDailyPapersSource(),
        OpenReviewSource(),
    ]

    all_papers: list[dict] = []

    for source in sources:
        try:
            logger.info("Querying source: %s", source.name)
            papers = source.discover(areas, since, queries=queries)
            logger.info("Source %s returned %d papers", source.name, len(papers))
            all_papers.extend(papers)
        except Exception:
            logger.exception(
                "Source %s failed — continuing with remaining sources",
                source.name,
            )

    logger.info("Total papers from all sources (before dedup): %d", len(all_papers))

    # Step 5: Deduplicate by title (case-insensitive) across sources
    unique_papers = _deduplicate_by_title(all_papers)
    logger.info("Unique papers after title dedup: %d", len(unique_papers))

    # Step 6: Batch LLM relevance filter — "is this in my ballpark?"
    from backend.shared.relevance_filter import batch_relevance_filter
    unique_papers = batch_relevance_filter(unique_papers, areas)
    candidates_found = len(unique_papers)
    logger.info("Papers after relevance filter: %d", candidates_found)

    # Step 6 & 7: Check DDB for existing papers, write new candidates
    discovered_at = datetime.now(timezone.utc).isoformat()
    new_candidates_written = 0
    duplicates_skipped = 0

    for paper in unique_papers:
        paper_id = paper.get("id", "")
        if not paper_id:
            logger.debug("Skipping paper with empty id: %s", paper.get("title", ""))
            continue

        # Check if we've already seen this paper
        if db.paper_exists(table, user_id, paper_id):
            duplicates_skipped += 1
            continue

        # Write the new candidate to DDB
        paper_record = _make_paper_record(paper, discovered_at)
        try:
            db.put_paper(table, user_id, paper_record)
            new_candidates_written += 1
        except Exception:
            logger.exception(
                "Failed to write paper %s to DDB — skipping", paper_id
            )

    summary = {
        "candidates_found": candidates_found,
        "new_candidates_written": new_candidates_written,
        "duplicates_skipped": duplicates_skipped,
    }
    logger.info("Discover step complete: %s", summary)
    return summary

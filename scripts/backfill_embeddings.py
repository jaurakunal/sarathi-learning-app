"""Backfill embeddings for existing papers.

Reads all papers from user's feed, creates global registry entries,
chunks + embeds each paper, stores in S3 Vectors.

Usage:
    AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python scripts/backfill_embeddings.py

Idempotent: skips papers already marked as embedded in the global registry.
"""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill")

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db
from backend.shared.chunker import chunk_paper_into_sections
from backend.shared.embeddings import embed_batch
from backend.shared.vectors import put_vectors

USER_ID = os.environ.get("USER_ID", "00000000-0000-0000-0000-000000000000")
TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
S3_BUCKET = os.environ.get("BUCKET_NAME", "sarathi-123456789012-us-east-1")
VECTOR_BUCKET = os.environ.get("VECTOR_BUCKET_NAME", "sarathi-vectors-123456789012-us-east-1")
VECTOR_INDEX = os.environ.get("VECTOR_INDEX_NAME", "paper-sections")

# Set env vars for shared modules that read from os.environ
os.environ.setdefault("BUCKET_NAME", S3_BUCKET)
os.environ.setdefault("VECTOR_BUCKET_NAME", VECTOR_BUCKET)
os.environ.setdefault("VECTOR_INDEX_NAME", VECTOR_INDEX)


def main():
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)
    s3_client = boto3.client("s3")

    # Get all feed cards for the user (each has a paper_id)
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"USER#{USER_ID}#FEED")
            & Key("SK").begins_with("CARD#")
        ),
    )
    cards = resp.get("Items", [])
    logger.info("Found %d feed cards for user %s", len(cards), USER_ID)

    # Dedupe by paper_id
    seen_papers: set = set()
    papers_to_process = []
    for card in cards:
        paper_id = card.get("paper_id", "")
        if paper_id and paper_id not in seen_papers:
            seen_papers.add(paper_id)
            papers_to_process.append({
                "paper_id": paper_id,
                "title": card.get("hook", paper_id)[:200],
                "source_url": card.get("source_url", ""),
                "full_text_s3_key": card.get("full_text_s3_key", f"users/{USER_ID}/papers/{paper_id}/full_text.txt"),
            })

    logger.info("Unique papers to process: %d", len(papers_to_process))

    embedded = 0
    skipped = 0
    failed = 0

    for paper in papers_to_process:
        paper_id = paper["paper_id"]

        # Check if already embedded globally
        if db.is_paper_embedded(table, paper_id):
            logger.info("  [SKIP] %s — already embedded", paper_id)
            skipped += 1
            continue

        # Create global registry entry
        db.put_global_paper(table, {
            "paper_id": paper_id,
            "title": paper["title"],
            "source_url": paper["source_url"],
            "sources": ["backfill"],
            "discovered_by": USER_ID,
        })

        # Read full text from S3
        s3_key = paper["full_text_s3_key"]
        try:
            resp = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
            full_text = resp["Body"].read().decode("utf-8")
        except Exception:
            logger.warning("  [FAIL] %s — could not read S3 key: %s", paper_id, s3_key)
            failed += 1
            continue

        if not full_text or len(full_text) < 100:
            logger.warning("  [FAIL] %s — full text too short (%d chars)", paper_id, len(full_text))
            failed += 1
            continue

        # Chunk into sections (no LLM — use regex/fallback for speed)
        logger.info("  [CHUNK] %s — %s", paper_id, paper["title"][:60])
        chunks = chunk_paper_into_sections(full_text, paper["title"], paper_id, use_llm=False)

        if not chunks:
            logger.warning("  [FAIL] %s — chunking produced 0 sections", paper_id)
            failed += 1
            continue

        # Embed
        logger.info("  [EMBED] %s — %d sections", paper_id, len(chunks))
        embeddings = embed_batch([c["chunk_text"] for c in chunks])

        # Store in S3 Vectors
        stored = put_vectors(chunks, embeddings)
        if stored > 0:
            db.mark_paper_embedded(table, paper_id, stored)
            logger.info("  [DONE] %s — %d vectors stored", paper_id, stored)
            embedded += 1
        else:
            logger.warning("  [FAIL] %s — vector storage failed", paper_id)
            failed += 1

        # Small delay between papers to avoid rate limiting
        time.sleep(1)

    logger.info("")
    logger.info("=" * 50)
    logger.info("Backfill complete:")
    logger.info("  Embedded: %d", embedded)
    logger.info("  Skipped (already done): %d", skipped)
    logger.info("  Failed: %d", failed)
    logger.info("  Total: %d", len(papers_to_process))


if __name__ == "__main__":
    main()

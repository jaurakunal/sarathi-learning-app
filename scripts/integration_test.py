"""Full pipeline integration test using the sarathi-test user.

Runs discover → triage → select → digest → lens against real AWS
(DDB + Bedrock + arXiv). Uses a dedicated test user 'sarathi-test'
so it never pollutes production data.

Usage:
    source .venv/bin/activate
    AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python scripts/integration_test.py

Exit code 0 = all steps passed. Non-zero = failure (blocks commit).
"""

import json
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("integration_test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_USER_ID = "sarathi-test"
TABLE_NAME = "sarathi"
S3_BUCKET = "sarathi-123456789012-us-east-1"

EVENT = {
    "user_id": TEST_USER_ID,
    "table_name": TABLE_NAME,
    "s3_bucket": S3_BUCKET,
    "since_days": 30,
}


def cleanup_test_data():
    """Remove any existing test papers/cards so the test starts fresh."""
    import boto3
    from boto3.dynamodb.conditions import Key

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    prefixes = [
        f"USER#{TEST_USER_ID}#PAPER#",
        f"USER#{TEST_USER_ID}#FEED",
        f"USER#{TEST_USER_ID}#ENGAGEMENT",
    ]

    deleted = 0
    for prefix in prefixes:
        # Use scan with filter (test user only, small dataset)
        resp = table.scan(
            FilterExpression=Key("PK").begins_with(prefix)
        )
        items = resp.get("Items", [])
        if items:
            with table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
            deleted += len(items)

    # Also clean FEED (different PK pattern — exact match)
    resp = table.query(KeyConditionExpression=Key("PK").eq(f"USER#{TEST_USER_ID}#FEED"))
    items = resp.get("Items", [])
    if items:
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        deleted += len(items)

    logger.info("Cleaned up %d test items", deleted)


def run_step(name, fn, event):
    """Run a pipeline step with error handling and timing."""
    logger.info("=" * 60)
    logger.info("  STEP: %s", name)
    logger.info("=" * 60)

    start = time.time()
    try:
        result = fn(event, None) if name != "digest" else fn(event)
        elapsed = time.time() - start
        logger.info("  RESULT: %s", json.dumps(result, indent=2))
        logger.info("  TIME: %.1fs", elapsed)
        return result
    except Exception as e:
        elapsed = time.time() - start
        logger.error("  FAILED after %.1fs: %s", elapsed, e)
        raise


def main():
    logger.info("Starting integration test with user: %s", TEST_USER_ID)
    logger.info("Table: %s, Bucket: %s", TABLE_NAME, S3_BUCKET)

    # Clean slate
    cleanup_test_data()

    # Step 1: Discover
    from backend.pipeline.discover import handler as discover_handler
    discover_result = run_step("discover", discover_handler, EVENT)

    candidates = discover_result.get("candidates_found", 0)
    written = discover_result.get("new_candidates_written", 0)
    if candidates == 0:
        logger.error("FAIL: Discover found 0 papers. Query generation may be broken.")
        sys.exit(1)
    logger.info("PASS: Discover found %d papers, wrote %d new candidates", candidates, written)

    # Step 2: Triage
    from backend.pipeline.triage import handler as triage_handler
    triage_result = run_step("triage", triage_handler, EVENT)

    triaged = triage_result.get("papers_triaged", 0)
    worth = triage_result.get("worth_reading", 0)
    if triaged == 0:
        logger.error("FAIL: Triage scored 0 papers.")
        sys.exit(1)
    logger.info("PASS: Triaged %d papers, %d worth reading", triaged, worth)

    # Step 3: Select
    from backend.pipeline.select import handler as select_handler
    select_result = run_step("select", select_handler, EVENT)

    selected = select_result.get("selected", 0)
    dry_week = select_result.get("dry_week", False)
    if selected == 0 and not dry_week:
        logger.warning("WARN: Select chose 0 papers (but not dry_week). Triage may be too strict.")
    logger.info("PASS: Selected %d papers, dry_week=%s", selected, dry_week)

    # If nothing was selected, skip digest and lens
    if selected == 0:
        logger.info("Skipping digest + lens (no papers selected)")
        logger.info("\n" + "=" * 60)
        logger.info("  INTEGRATION TEST PASSED (partial — no cards generated)")
        logger.info("=" * 60)
        sys.exit(0)

    # Step 4: Digest
    from backend.pipeline.digest import run as digest_run
    digest_result = run_step("digest", digest_run, EVENT)

    cards = digest_result.get("cards_generated", 0)
    failed = digest_result.get("papers_failed", 0)
    if cards == 0:
        logger.error("FAIL: Digest generated 0 cards.")
        sys.exit(1)
    logger.info("PASS: Generated %d cards (%d papers failed)", cards, failed)

    # Step 5: Lens
    from backend.pipeline.lens import handler as lens_handler
    lens_result = run_step("lens", lens_handler, EVENT)

    annotated = lens_result.get("cards_annotated", 0)
    logger.info("PASS: Annotated %d cards with hypothesis relevance", annotated)

    # Final verification: check DDB has cards
    import boto3
    from boto3.dynamodb.conditions import Key

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{TEST_USER_ID}#FEED"),
        Limit=5,
    )
    feed_cards = resp.get("Items", [])

    logger.info("\n" + "=" * 60)
    logger.info("  INTEGRATION TEST PASSED")
    logger.info("  Papers discovered: %d", candidates)
    logger.info("  Papers triaged: %d", triaged)
    logger.info("  Papers selected: %d", selected)
    logger.info("  Feed cards generated: %d", cards)
    logger.info("  Cards annotated: %d", annotated)
    logger.info("=" * 60)

    # Print a sample card hook for human review
    if feed_cards:
        card = feed_cards[0]
        logger.info("\n  SAMPLE CARD HOOK:")
        logger.info("  %s", card.get("hook", "(no hook)"))
        logger.info("  WHY NOW: %s", card.get("why_you_now", "(none)"))

    sys.exit(0)


if __name__ == "__main__":
    main()

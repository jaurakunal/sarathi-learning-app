"""Pipeline step: Select top papers within time budget.

After Triage promotes papers to status="surfaced", Select applies a time-budget
cap so we don't overwhelm the user with too many papers in a single run.
Papers beyond the cap are demoted back to "skipped".
"""

from __future__ import annotations

import logging
from decimal import Decimal

import boto3

from backend.shared import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_MAX_CARDS = 5


def handler(event: dict, context) -> dict:
    """Lambda handler for the Select step.

    Reads all surfaced papers, sorts by triage_score descending, keeps the
    top N (max_cards) and demotes the rest back to "skipped". Flags a dry
    week if zero papers survived triage.

    Event:
        user_id: str — the user to select papers for
        table_name: str — DynamoDB table name
        max_cards: int (optional) — max papers to keep per run, default 5
    """
    user_id = event["user_id"]
    workspace_id = event.get("workspace_id", "")
    table_name = event["table_name"]
    max_cards = int(event.get("max_cards", DEFAULT_MAX_CARDS))

    # Set up DynamoDB table resource
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    if not workspace_id:
        workspace_id = db.get_active_workspace(table, user_id) or ""

    # 1. Load all surfaced papers from this run
    surfaced = db.list_papers_by_status(table, user_id, workspace_id, "surfaced")

    # 2. Handle dry week — nothing survived triage
    if not surfaced:
        logger.info("Dry week for user %s: no surfaced papers to select from.", user_id)
        return {"selected": 0, "skipped_over_budget": 0, "dry_week": True}

    # 3. Sort by triage_score descending (handle Decimal from DDB gracefully)
    surfaced.sort(key=lambda p: float(p.get("triage_score", 0)), reverse=True)

    # 4. Split into keepers vs over-budget
    selected_papers = surfaced[:max_cards]
    over_budget_papers = surfaced[max_cards:]

    # 5. Demote over-budget papers back to "skipped"
    for paper in over_budget_papers:
        paper["status"] = "skipped"
        paper["skip_reason"] = "over_time_budget"
        db.put_paper(table, user_id, workspace_id, paper)
        logger.info(
            "Demoted paper %s (score=%.2f) — over time budget.",
            paper.get("id", "unknown"),
            float(paper.get("triage_score", 0)),
        )

    selected_count = len(selected_papers)
    skipped_count = len(over_budget_papers)

    logger.info(
        "Select complete for user %s: %d selected, %d skipped (over budget).",
        user_id,
        selected_count,
        skipped_count,
    )

    return {
        "selected": selected_count,
        "skipped_over_budget": skipped_count,
        "dry_week": False,
    }

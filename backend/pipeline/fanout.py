"""Fan-out Lambda: triggers one pipeline execution per (user, workspace) pair.

Called by EventBridge nightly. Reads active users from DDB, then for each user
reads their list of active workspaces, and starts one Step Function execution
per active workspace. Auto-pauses users inactive >3 days (by clearing global
SYSTEM#USERS.status); per-workspace pause is honored via the workspace status.

Deduplication uses a per-workspace DDB record
(PK=USER#{user_id}#WS#{wid}#PIPELINE, SK=LATEST).
"""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db

logger = logging.getLogger(__name__)

INACTIVE_DAYS = 3

# Spread the nightly burst across a window so we don't hit Bedrock all at once.
# Each execution waits a random 0..JITTER_MAX_SECONDS in the state machine.
JITTER_MAX_SECONDS = int(os.environ.get("JITTER_MAX_SECONDS", "3600"))


def _can_trigger(table, sfn, user_id: str, workspace_id: str) -> bool:
    """Check if we can trigger a new pipeline for this (user, workspace)."""
    run = db.get_pipeline_run(table, user_id, workspace_id)
    if not run or run.get("status") != "running":
        return True
    try:
        desc = sfn.describe_execution(executionArn=run["execution_arn"])
        actual_status = desc["status"]
        if actual_status == "RUNNING":
            return False
        mapped = {"SUCCEEDED": "succeeded", "FAILED": "failed"}.get(actual_status, "failed")
        db.update_pipeline_status(table, user_id, workspace_id, mapped)
        return True
    except Exception:
        return True


def handler(event: dict, context) -> dict:
    table_name = os.environ.get("TABLE_NAME", "sarathi")
    state_machine_arn = os.environ.get("STATE_MACHINE_ARN", "")
    s3_bucket = os.environ.get("BUCKET_NAME", "")

    if not state_machine_arn:
        logger.error("STATE_MACHINE_ARN not set")
        return {"users_triggered": 0}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # List all active users
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq("SYSTEM#USERS")
            & Key("SK").begins_with("USER#")
        ),
    )
    users = [item for item in resp.get("Items", []) if item.get("status") == "active"]

    if not users:
        logger.info("No active users found")
        return {"users_triggered": 0, "workspaces_triggered": 0}

    sfn = boto3.client("stepfunctions")
    triggered = 0
    paused = 0
    skipped = 0
    no_workspace = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=INACTIVE_DAYS)).isoformat()

    for user in users:
        user_id = user.get("user_id", "")
        if not user_id:
            continue

        # Iterate over the user's workspaces
        workspaces = db.list_workspaces(table, user_id)
        if not workspaces:
            no_workspace += 1
            logger.info("User %s has no workspaces — skipping", user_id)
            continue

        for ws in workspaces:
            wid = ws.get("workspace_id", "")
            if not wid:
                continue
            if ws.get("status") != "active":
                logger.info(
                    "Skipping workspace %s/%s (status=%s)",
                    user_id, wid, ws.get("status"),
                )
                continue

            # Auto-pause inactive workspaces (per-workspace, not per-user)
            ws_last_active = ws.get("last_active_at", "")
            if ws_last_active and ws_last_active < cutoff:
                db.update_workspace(
                    table, user_id, wid,
                    status="paused",
                    paused_reason="inactive",
                )
                paused += 1
                logger.info(
                    "Auto-paused inactive workspace %s/%s (last active: %s)",
                    user_id, wid, ws_last_active,
                )
                continue

            if not _can_trigger(table, sfn, user_id, wid):
                skipped += 1
                logger.info("Skipped %s/%s — pipeline already running", user_id, wid)
                continue

            try:
                resp_sfn = sfn.start_execution(
                    stateMachineArn=state_machine_arn,
                    input=json.dumps({
                        "user_id": user_id,
                        "workspace_id": wid,
                        "table_name": table_name,
                        "s3_bucket": s3_bucket,
                        "since_days": 30,
                        # Stagger the nightly burst; state machine waits this long.
                        "jitter_seconds": random.randint(0, JITTER_MAX_SECONDS),
                    }),
                )
                execution_arn = resp_sfn.get("executionArn", "")
                db.put_pipeline_run(table, user_id, wid, execution_arn, "running")
                triggered += 1
                logger.info("Triggered pipeline for %s/%s", user_id, wid)
            except Exception:
                logger.exception("Failed to trigger pipeline for %s/%s", user_id, wid)

    logger.info(
        "Fan-out complete: %d workspaces triggered, %d workspaces auto-paused, %d workspaces skipped, %d users without workspaces",
        triggered, paused, skipped, no_workspace,
    )
    from backend.shared import metrics
    metrics.emit("PipelineExecutionsStarted", triggered)
    metrics.emit("WorkspacesAutoPaused", paused)
    return {
        "workspaces_triggered": triggered,
        "users_paused": paused,
        "workspaces_skipped": skipped,
        "users_without_workspaces": no_workspace,
        # legacy alias
        "users_triggered": triggered,
        "users_skipped": skipped,
    }

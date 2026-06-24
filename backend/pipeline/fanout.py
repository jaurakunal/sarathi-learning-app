"""Fan-out Lambda: triggers one pipeline execution per active user.

Called by EventBridge nightly. Reads active users from DDB, starts a
Step Function execution for each. Auto-pauses users inactive >7 days.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

INACTIVE_DAYS = 7


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
        return {"users_triggered": 0}

    sfn = boto3.client("stepfunctions")
    triggered = 0
    paused = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=INACTIVE_DAYS)).isoformat()

    for user in users:
        user_id = user.get("user_id", "")
        if not user_id:
            continue

        # Auto-pause inactive users
        last_active = user.get("last_active_at", "")
        if last_active and last_active < cutoff:
            table.update_item(
                Key={"PK": "SYSTEM#USERS", "SK": f"USER#{user_id}"},
                UpdateExpression="SET #s = :s, paused_reason = :r",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "paused",
                    ":r": "inactive_7_days",
                },
            )
            paused += 1
            logger.info("Auto-paused inactive user %s (last active: %s)", user_id, last_active)
            continue

        try:
            sfn.start_execution(
                stateMachineArn=state_machine_arn,
                input=json.dumps({
                    "user_id": user_id,
                    "table_name": table_name,
                    "s3_bucket": s3_bucket,
                    "since_days": 30,
                }),
            )
            triggered += 1
            logger.info("Triggered pipeline for user %s", user_id)
        except Exception:
            logger.exception("Failed to trigger pipeline for user %s", user_id)

    logger.info("Fan-out complete: %d triggered, %d auto-paused", triggered, paused)
    return {"users_triggered": triggered, "users_paused": paused}

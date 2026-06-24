"""Fan-out Lambda: triggers one pipeline execution per active user.

Called by EventBridge nightly. Reads active users from DDB, starts a
Step Function execution for each.
"""

from __future__ import annotations

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)


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

    for user in users:
        user_id = user.get("user_id", "")
        if not user_id:
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

    logger.info("Fan-out complete: %d users triggered", triggered)
    return {"users_triggered": triggered}

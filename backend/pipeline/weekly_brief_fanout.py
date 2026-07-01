"""Weekly fan-out Lambda: invoke weekly_brief for each (user, workspace) pair.

Triggered by EventBridge weekly. Reads SYSTEM#USERS, then for each user
reads their list of active workspaces, and invokes the weekly_brief
handler asynchronously per active workspace.
"""

from __future__ import annotations

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db

logger = logging.getLogger(__name__)


def handler(event: dict, context) -> dict:
    table_name = os.environ.get("TABLE_NAME", "sarathi")
    brief_function_name = os.environ.get("BRIEF_FUNCTION_NAME", "sarathi-weekly-brief")

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq("SYSTEM#USERS") & Key("SK").begins_with("USER#")
        ),
    )
    users = [u for u in resp.get("Items", []) if u.get("status") == "active"]

    if not users:
        logger.info("No active users for weekly brief")
        return {"users_triggered": 0, "workspaces_triggered": 0}

    lambda_client = boto3.client("lambda")
    triggered = 0
    for user in users:
        uid = user.get("user_id", "")
        if not uid:
            continue
        workspaces = db.list_workspaces(table, uid)
        for ws in workspaces:
            wid = ws.get("workspace_id", "")
            if not wid or ws.get("status") != "active":
                continue
            try:
                lambda_client.invoke(
                    FunctionName=brief_function_name,
                    InvocationType="Event",
                    Payload=json.dumps({
                        "user_id": uid,
                        "workspace_id": wid,
                        "table_name": table_name,
                    }),
                )
                triggered += 1
                logger.info("Triggered weekly brief for %s/%s", uid, wid)
            except Exception:
                logger.exception("Failed to trigger weekly brief for %s/%s", uid, wid)

    logger.info("Weekly brief fanout: %d (user, workspace) pairs triggered", triggered)
    return {"workspaces_triggered": triggered, "users_triggered": triggered}

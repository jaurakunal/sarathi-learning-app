"""API handler for user settings: pipeline pause/resume, account deletion."""

from __future__ import annotations

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


def _get_user_id(event: dict) -> str:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    return claims.get("sub", "")


def handler(event: dict, context) -> dict:
    """
    PUT /settings/pipeline — pause/resume pipeline for this user
    DELETE /settings/delete-account — delete all user data
    """
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    method = event.get("httpMethod", "")
    path = event.get("path", "")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    if method == "PUT" and "pipeline" in path:
        body = json.loads(event.get("body") or "{}")
        status = body.get("status", "active")
        if status not in ("active", "paused"):
            return _response(400, {"error": "status must be active or paused"})

        table.update_item(
            Key={"PK": "SYSTEM#USERS", "SK": f"USER#{user_id}"},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status},
        )
        return _response(200, {"status": status})

    elif method == "DELETE" and "delete-account" in path:
        _delete_all_user_data(table, user_id)
        return _response(200, {"status": "deleted"})

    elif method == "GET":
        # Return current settings
        resp = table.get_item(
            Key={"PK": "SYSTEM#USERS", "SK": f"USER#{user_id}"},
        )
        item = resp.get("Item", {})
        return _response(200, {
            "pipeline_status": item.get("status", "active"),
        })

    return _response(405, {"error": "Method not allowed"})


def _delete_all_user_data(table, user_id: str) -> None:
    """Delete ALL data for a user across all PK patterns."""
    prefixes = [
        f"USER#{user_id}#FEED",
        f"USER#{user_id}#PROFILE",
        f"USER#{user_id}#ENGAGEMENT",
        f"USER#{user_id}#PROFILE_HISTORY",
        f"USER#{user_id}#PUSH",
    ]

    # Delete items under known PK prefixes
    for pk in prefixes:
        resp = table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ProjectionExpression="PK, SK",
        )
        with table.batch_writer() as batch:
            for item in resp.get("Items", []):
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    # Delete conversations (need to find them via GSI1)
    conv_resp = table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("gsi1pk").eq(f"USER#{user_id}"),
        ProjectionExpression="conv_id",
    )
    for conv in conv_resp.get("Items", []):
        conv_id = conv.get("conv_id", "")
        if conv_id:
            pk = f"USER#{user_id}#CONV#{conv_id}"
            items_resp = table.query(
                KeyConditionExpression=Key("PK").eq(pk),
                ProjectionExpression="PK, SK",
            )
            with table.batch_writer() as batch:
                for item in items_resp.get("Items", []):
                    batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    # Delete papers
    paper_resp = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("gsi2pk").begins_with(f"USER#{user_id}#PAPER_STATUS"),
        ProjectionExpression="PK, SK",
    )
    with table.batch_writer() as batch:
        for item in paper_resp.get("Items", []):
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    # Remove from active users
    table.delete_item(Key={"PK": "SYSTEM#USERS", "SK": f"USER#{user_id}"})

    logger.info("Deleted all data for user %s", user_id)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,PUT,DELETE,OPTIONS",
        },
        "body": json.dumps(body),
    }

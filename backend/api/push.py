"""API handler for push subscription management."""

from __future__ import annotations

import json
import logging
import os

import boto3

from backend.shared import db

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


def handler(event: dict, context) -> dict:
    """Handle POST /push/subscribe and DELETE /push/subscribe."""
    method = event.get("httpMethod", "")
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Authorization,Content-Type",
        "Access-Control-Allow-Methods": "POST,DELETE,OPTIONS",
    }

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": headers, "body": ""}

    # Auth
    claims = (event.get("requestContext", {}).get("authorizer", {}).get("claims", {}))
    user_id = claims.get("sub", "")
    if not user_id:
        return {"statusCode": 401, "headers": headers, "body": json.dumps({"error": "Unauthorized"})}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    body = json.loads(event.get("body", "{}") or "{}")

    if method == "POST":
        subscription = body.get("subscription")
        if not subscription or not subscription.get("endpoint") or not subscription.get("keys"):
            return {"statusCode": 400, "headers": headers,
                    "body": json.dumps({"error": "subscription with endpoint and keys required"})}

        db.put_push_subscription(table, user_id, subscription)
        return {"statusCode": 200, "headers": headers, "body": json.dumps({"status": "subscribed"})}

    elif method == "DELETE":
        endpoint = body.get("endpoint", "")
        if not endpoint:
            return {"statusCode": 400, "headers": headers,
                    "body": json.dumps({"error": "endpoint required"})}

        db.delete_push_subscription(table, user_id, endpoint)
        return {"statusCode": 200, "headers": headers, "body": json.dumps({"status": "unsubscribed"})}

    return {"statusCode": 405, "headers": headers, "body": json.dumps({"error": "Method not allowed"})}

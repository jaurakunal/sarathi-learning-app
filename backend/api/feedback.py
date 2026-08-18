"""API handler: in-app user feedback → Slack.

POST /feedback  { "message": str, "category"?: "bug"|"idea"|"other" }

Posts the feedback to Slack (via AWS Chatbot custom notification on an SNS
topic — same mechanism as the product digest) with a machine-parseable DEBUG
METADATA block so an ops/fixing agent can pick up the report, correlate it to
logs, and investigate. The debug block carries the timestamp, user sub + email,
active workspace, app version, and the API Gateway request id / user agent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from backend.api._workspace_helper import get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
FEEDBACK_TOPIC_ARN = os.environ.get("FEEDBACK_TOPIC_ARN", "")
APP_VERSION = os.environ.get("APP_VERSION", "unknown")

VALID_CATEGORIES = {"bug", "idea", "other"}
MAX_MESSAGE_LEN = 4000


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def _claims(event: dict) -> dict:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    ) or {}


def handler(event: dict, context) -> dict:
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"ok": True})

    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _response(400, {"error": "Invalid JSON body"})

    message = (body.get("message") or "").strip()
    if not message:
        return _response(400, {"error": "message is required"})
    message = message[:MAX_MESSAGE_LEN]

    category = (body.get("category") or "other").lower()
    if category not in VALID_CATEGORIES:
        category = "other"

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)
    workspace_id = resolve_workspace_id(table, event, user_id) or ""

    claims = _claims(event)
    rc = event.get("requestContext", {})
    identity = rc.get("identity", {}) or {}
    # Debug metadata for a fixing agent — timestamp + everything needed to
    # correlate this report to logs and reproduce.
    debug = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user_id": user_id,
        "email": claims.get("email", ""),
        "workspace_id": workspace_id,
        "category": category,
        "app_version": APP_VERSION,
        "request_id": rc.get("requestId", ""),
        "api_stage": rc.get("stage", ""),
        "user_agent": identity.get("userAgent", ""),
        "source_ip": identity.get("sourceIp", ""),
    }

    emoji = {"bug": "🐛", "idea": "💡", "other": "💬"}.get(category, "💬")
    description = (
        f"*{category.upper()}* from `{debug['email'] or user_id}`\n\n"
        f"{message}\n\n"
        f"*Debug (for the fixing agent):*\n"
        f"```json\n{json.dumps(debug, indent=2)}\n```"
    )
    payload = {
        "version": "1.0",
        "source": "custom",
        "content": {
            "title": f"{emoji} Sārathi feedback — {category}",
            "description": description,
        },
    }

    if not FEEDBACK_TOPIC_ARN:
        logger.warning("FEEDBACK_TOPIC_ARN not set — logging feedback instead of posting")
        logger.info("FEEDBACK %s", json.dumps({"message": message, **debug}))
        return _response(200, {"status": "received"})

    boto3.client("sns").publish(
        TopicArn=FEEDBACK_TOPIC_ARN,
        Message=json.dumps(payload),
        Subject="Sarathi feedback",
    )
    logger.info("Feedback posted: category=%s user=%s ws=%s", category, user_id, workspace_id)
    return _response(200, {"status": "received"})

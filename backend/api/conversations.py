"""API handler for conversation management."""

from __future__ import annotations

import json
import logging
import os
import uuid

import boto3

from backend.shared import db
from backend.api._workspace_helper import get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


def handler(event: dict, context) -> dict:
    """
    GET /conversations — list all conversations
    POST /conversations — create a new research conversation
    PUT /conversations/{conv_id} — update conversation title
    DELETE /conversations/{conv_id} — delete a conversation
    """
    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    if method == "OPTIONS":
        return _response(200, {})

    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    if method == "PUT":
        conv_id = path_params.get("conv_id", "")
        body = json.loads(event.get("body") or "{}")
        if not conv_id:
            conv_id = body.get("conv_id", "")
        title = body.get("title", "")
        if not conv_id or not title:
            return _response(400, {"error": "conv_id and title required"})
        db.update_conversation_title(table, user_id, workspace_id, conv_id, title)
        return _response(200, {"status": "updated"})

    if method == "GET":
        convs = db.list_all_conversations(table, user_id, workspace_id)

        paper_hooks = {}
        for conv in convs:
            if conv.get("scope") != "research" and not conv.get("title"):
                pid = conv.get("paper_id") or conv.get("conv_id", "")
                if pid and pid not in paper_hooks:
                    card = db.get_feed_card_by_paper(table, user_id, workspace_id, pid)
                    if card:
                        paper_hooks[pid] = card.get("hook", "")[:60]

        result = []
        for conv in convs:
            title = conv.get("title", "")
            if not title and conv.get("scope") != "research":
                pid = conv.get("paper_id") or conv.get("conv_id", "")
                title = paper_hooks.get(pid, pid[:20])
            result.append({
                "conv_id": conv.get("conv_id", ""),
                "scope": conv.get("scope", "paper"),
                "title": title,
                "paper_id": conv.get("paper_id", ""),
                "last_active": conv.get("last_active", ""),
                "turn_count": int(conv.get("turn_count", 0)),
            })
        return _response(200, {"conversations": result, "workspace_id": workspace_id})

    elif method == "POST":
        body = json.loads(event.get("body") or "{}")
        title = body.get("title", "")
        conv_id = str(uuid.uuid4())[:12]
        conv = db.create_research_conversation(
            table, user_id, workspace_id, conv_id, title
        )
        return _response(201, {
            "conv_id": conv["conv_id"],
            "title": conv["title"],
            "scope": "research",
        })

    elif method == "DELETE":
        conv_id = path_params.get("conv_id", "")
        if not conv_id:
            body = json.loads(event.get("body") or "{}")
            conv_id = body.get("conv_id", "")
        if not conv_id:
            return _response(400, {"error": "conv_id required"})
        db.delete_conversation(table, user_id, workspace_id, conv_id)
        return _response(200, {"status": "deleted"})

    return _response(405, {"error": "Method not allowed"})


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }

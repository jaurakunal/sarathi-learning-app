"""AppSync resolver: dispatches streaming chat to async Lambda.

Returns immediately with conversationId + turnSeq. The actual LLM streaming
happens in chat_stream Lambda invoked asynchronously.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from backend.shared import db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
STREAM_FUNCTION_NAME = os.environ.get("STREAM_FUNCTION_NAME", "sarathi-chat-stream")


def _safe_metric(name: str, value: float, dimensions: dict | None = None) -> None:
    try:
        from backend.shared import metrics
        metrics.emit(name, value, dimensions=dimensions)
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def handler(event: dict, context) -> dict:
    """AppSync Lambda resolver for sendMessage mutation.

    Validates, creates the DDB turn, invokes streaming Lambda async, returns immediately.
    """
    identity = event.get("identity", {})
    user_id = identity.get("sub", "")
    if not user_id:
        claims = identity.get("claims", {})
        user_id = claims.get("sub", "")

    if not user_id:
        return {"conversationId": "", "turnSeq": 0, "status": "error:unauthorized"}

    args = event.get("arguments", {})
    paper_id = args.get("paperId", "")
    message = args.get("message", "").strip()
    workspace_id = args.get("workspaceId") or ""

    if not paper_id or not message:
        return {"conversationId": "", "turnSeq": 0, "status": "error:missing_fields"}

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    if not workspace_id:
        workspace_id = db.get_active_workspace(table, user_id) or ""
    if not workspace_id:
        return {"conversationId": "", "turnSeq": 0, "status": "error:no_workspace"}

    # Determine scope: paper or research conversation
    conv = db.get_conversation_by_paper(table, user_id, workspace_id, paper_id)
    scope = "paper"

    if conv is None:
        check = table.get_item(
            Key={
                "PK": db._conv_pk(user_id, workspace_id, paper_id),
                "SK": "META",
            },
        )
        if check.get("Item") and check["Item"].get("scope") == "research":
            conv = check["Item"]
            scope = "research"
        else:
            full_text_s3_key = f"users/{user_id}/papers/{paper_id}/full_text.txt"
            conv = db.create_conversation(
                table, user_id, workspace_id, paper_id, full_text_s3_key
            )

    conv_id = conv.get("conv_id", paper_id)

    turns = db.get_conversation_turns(table, user_id, workspace_id, conv_id)
    seq = len(turns) + 1
    request_ts = _now_iso()

    db.put_turn(table, user_id, workspace_id, conv_id, seq, message, request_ts)
    db.update_conversation_last_active(table, user_id, workspace_id, conv_id)

    lambda_client = boto3.client("lambda")
    try:
        lambda_client.invoke(
            FunctionName=STREAM_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps({
                "user_id": user_id,
                "workspace_id": workspace_id,
                "paper_id": paper_id if scope == "paper" else "",
                "conv_id": conv_id,
                "message": message,
                "turn_seq": seq,
                "scope": scope,
            }),
        )
    except Exception:
        # The turn is already written; if we can't kick off the stream the
        # client would otherwise hang forever. Surface an error instead.
        logger.exception("Failed to dispatch stream Lambda for conv=%s ws=%s", conv_id, workspace_id)
        _safe_metric("ChatStreamDispatchFailed", 1)
        return "error:dispatch_failed"

    logger.info("Dispatched stream for conv=%s ws=%s scope=%s turn=%d", conv_id, workspace_id, scope, seq)
    _safe_metric("ChatStreamStarted", 1)
    return {"conversationId": conv_id, "turnSeq": seq, "status": "ok"}

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def handler(event: dict, context) -> dict:
    """AppSync Lambda resolver for sendMessage mutation.

    Validates, creates the DDB turn, invokes streaming Lambda async, returns immediately.
    """
    # Extract user identity from Cognito claims in AppSync context
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

    if not paper_id or not message:
        return {"conversationId": "", "turnSeq": 0, "status": "error:missing_fields"}

    # Set up DDB
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    # Determine scope: check if this is a research conversation or paper chat
    # Research conversations have a short uuid-style conv_id, papers have longer IDs
    conv = db.get_conversation_by_paper(table, user_id, paper_id)
    scope = "paper"

    if conv is None:
        # Check if it's a research conversation (conv_id passed as paperId)
        from boto3.dynamodb.conditions import Key
        check = table.get_item(
            Key={"PK": f"USER#{user_id}#CONV#{paper_id}", "SK": "META"},
        )
        if check.get("Item") and check["Item"].get("scope") == "research":
            conv = check["Item"]
            scope = "research"
        else:
            # Create new paper conversation
            full_text_s3_key = f"users/{user_id}/papers/{paper_id}/full_text.txt"
            conv = db.create_conversation(table, user_id, paper_id, full_text_s3_key)

    conv_id = conv.get("conv_id", paper_id)

    # Get existing turns to determine seq
    turns = db.get_conversation_turns(table, user_id, conv_id)
    seq = len(turns) + 1
    request_ts = _now_iso()

    # Write turn with request (response=null) — immediate durability
    db.put_turn(table, user_id, conv_id, seq, message, request_ts)
    db.update_conversation_last_active(table, user_id, conv_id)

    # Invoke streaming Lambda asynchronously
    lambda_client = boto3.client("lambda")
    lambda_client.invoke(
        FunctionName=STREAM_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps({
            "user_id": user_id,
            "paper_id": paper_id if scope == "paper" else "",
            "conv_id": conv_id,
            "message": message,
            "turn_seq": seq,
            "scope": scope,
        }),
    )

    logger.info("Dispatched stream for conv=%s scope=%s turn=%d", conv_id, scope, seq)
    return {"conversationId": conv_id, "turnSeq": seq, "status": "ok"}

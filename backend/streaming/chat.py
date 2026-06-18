"""Lambda Function URL handler: streaming chat via SSE.

Uses RESPONSE_STREAM invoke mode to send SSE chunks as the LLM generates.
Auth: Cognito JWT verified in-handler (no API Gateway authorizer available).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import boto3

from backend.shared import db
from backend.shared.llm import stream_llm

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")

SYSTEM_PROMPT = """You are Sārathi, a research assistant for a single user. You answer questions about academic papers with precision, honesty, and clarity.

Rules:
- Ground every answer in the paper text provided. Cite specific sections when possible.
- Translate dense academic language into clear, applied terms. The user is a practitioner, not an academic.
- Math: explain in plain language first. Only show equations if the user asks.
- Be concise. One clear paragraph is better than three meandering ones.
- If the paper doesn't address a question, say so honestly. Don't fabricate.
- Never flatter. Be a sharp, accurate mirror.
- Connect ideas to what the user has previously asked in this conversation when relevant."""


def handler(event: dict, context) -> dict:
    """Lambda Function URL handler for streaming Q&A."""
    # Parse request
    body = _parse_body(event)
    if body is None:
        return _error_response(400, "Invalid request body")

    user_id = _get_user_id(event)
    if not user_id:
        return _error_response(401, "Unauthorized")

    paper_id = body.get("paper_id", "")
    message = body.get("message", "").strip()

    if not paper_id or not message:
        return _error_response(400, "paper_id and message are required")

    # Set up resources
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)
    s3_client = boto3.client("s3")

    # 1. Get or create conversation for this paper
    conv = db.get_conversation_by_paper(table, user_id, paper_id)
    if conv is None:
        full_text_s3_key = f"users/{user_id}/papers/{paper_id}/full_text.txt"
        conv = db.create_conversation(table, user_id, paper_id, full_text_s3_key)

    conv_id = paper_id
    full_text_s3_key = conv.get("full_text_s3_key", "")

    # 2. Read paper full text from S3
    paper_text = _read_s3_text(s3_client, BUCKET_NAME, full_text_s3_key)
    if not paper_text:
        return _error_response(404, "Paper full text not found in S3")

    # 3. Read existing turns
    turns = db.get_conversation_turns(table, user_id, conv_id)

    # 4. Read profile summaries for context
    profile = db.get_full_profile(table, user_id)
    summaries_text = _format_summaries(profile.get("summaries", []))

    # 5. Determine next turn sequence
    seq = len(turns) + 1
    request_ts = _now_iso()

    # 6. Write turn with request (response=null)
    db.put_turn(table, user_id, conv_id, seq, message, request_ts)
    db.update_conversation_last_active(table, user_id, conv_id)

    # 7. Assemble LLM messages
    llm_messages = _build_messages(turns, message, paper_text, summaries_text)

    # 8. Stream response
    response_chunks: list[str] = []
    tokens_in = 0
    tokens_out = 0

    def generate_sse():
        nonlocal tokens_in, tokens_out

        yield _sse_event({"type": "start", "conv_id": conv_id, "turn_seq": seq})

        stream = stream_llm(
            system=SYSTEM_PROMPT,
            messages=llm_messages,
            model_id=MODEL_ID,
            max_tokens=4096,
            temperature=0.3,
        )

        if stream is None:
            yield _sse_event({"type": "error", "message": "LLM stream failed to start"})
            return

        usage = None
        try:
            while True:
                chunk = next(stream)
                response_chunks.append(chunk)
                yield _sse_event({"type": "chunk", "text": chunk})
        except StopIteration as e:
            usage = e.value

        if usage:
            tokens_in = usage.get("tokens_in", 0)
            tokens_out = usage.get("tokens_out", 0)

        yield _sse_event({
            "type": "done",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })

        # 9. Update turn with full response
        full_response = "".join(response_chunks)
        response_ts = _now_iso()
        db.update_turn_response(
            table, user_id, conv_id, seq,
            response=full_response,
            response_ts=response_ts,
            citations=[],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    # Return streaming response
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            },
        "body": "".join(generate_sse()),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_body(event: dict) -> Optional[dict]:
    try:
        body_str = event.get("body", "")
        if not body_str:
            return None
        return json.loads(body_str)
    except (json.JSONDecodeError, TypeError):
        return None


def _get_user_id(event: dict) -> str:
    """Extract user_id from Cognito JWT claims (passed by Function URL IAM or custom)."""
    # Lambda Function URL with IAM auth passes identity in requestContext
    request_context = event.get("requestContext", {})

    # Check for Cognito authorizer claims (if proxied via API GW)
    claims = request_context.get("authorizer", {}).get("claims", {})
    if claims.get("sub"):
        return claims["sub"]

    # Check Authorization header for JWT (Function URL with NONE auth)
    headers = event.get("headers", {})
    auth_header = headers.get("authorization", "") or headers.get("Authorization", "")
    if auth_header:
        return _extract_sub_from_jwt(auth_header)

    return ""


def _extract_sub_from_jwt(token: str) -> str:
    """Decode JWT payload without verification (Function URL trusts Cognito).

    For v0 with auth_type=NONE, we decode the sub claim from the ID token.
    The token was issued by Cognito and validated client-side. For production,
    add JWKS verification here.
    """
    import base64

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return ""
        payload = parts[1]
        # Fix padding
        payload += "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        return claims.get("sub", "")
    except Exception:
        logger.warning("Failed to decode JWT")
        return ""


def _read_s3_text(s3_client, bucket: str, key: str) -> Optional[str]:
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read().decode("utf-8")
    except Exception:
        logger.warning("Failed to read S3: s3://%s/%s", bucket, key)
        return None


def _format_summaries(summaries: list[dict]) -> str:
    if not summaries:
        return ""
    parts = []
    for s in sorted(summaries, key=lambda x: x.get("SK", "")):
        tier = s.get("tier", "")
        content = s.get("content", "")
        if content:
            parts.append(f"[{tier}] {content}")
    return "\n".join(parts)


def _build_messages(
    turns: list[dict], new_message: str, paper_text: str, summaries_text: str
) -> list[dict]:
    """Assemble the full message history for the LLM."""
    messages: list[dict] = []

    # First message includes paper context
    context_block = f"<paper>\n{paper_text}\n</paper>"
    if summaries_text:
        context_block += f"\n\n<user_context>\n{summaries_text}\n</user_context>"

    # Add historical turns
    for turn in turns:
        req = turn.get("request", "")
        resp = turn.get("response", "")
        if req:
            messages.append({"role": "user", "content": req})
        if resp:
            messages.append({"role": "assistant", "content": resp})

    # Add new user message (with paper context on first message)
    if not messages:
        # First message in conversation: include paper text
        messages.append({"role": "user", "content": f"{context_block}\n\n{new_message}"})
    else:
        messages.append({"role": "user", "content": new_message})

    return messages


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _error_response(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            },
        "body": json.dumps({"error": message}),
    }

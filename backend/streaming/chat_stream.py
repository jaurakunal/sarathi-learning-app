"""AppSync-backed streaming chat Lambda.

Invoked by AppSync sendMessage mutation. Streams tokens from Bedrock
and publishes each chunk back to AppSync via publishChunk mutation,
which triggers the onChunk subscription for the frontend.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import urllib.error
import boto3
from botocore.config import Config
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
import urllib.request

from backend.shared import db
from backend.streaming.chat import (
    _build_system_prompt,
    _build_system_prompt_with_retrieval,
    _build_messages,
    _read_s3_text,
    _format_retrieved_chunks,
    _format_summaries,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
APPSYNC_ENDPOINT = os.environ.get("APPSYNC_ENDPOINT", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _publish_chunk(
    conversation_id: str, turn_seq: int, chunk: str, done: bool,
    tokens_in: int = 0, tokens_out: int = 0,
) -> None:
    """Publish a chunk to AppSync via IAM-signed HTTP request."""
    mutation = """
    mutation PublishChunk(
        $conversationId: String!,
        $turnSeq: Int!,
        $chunk: String!,
        $done: Boolean!,
        $tokensIn: Int,
        $tokensOut: Int
    ) {
        publishChunk(
            conversationId: $conversationId,
            turnSeq: $turnSeq,
            chunk: $chunk,
            done: $done,
            tokensIn: $tokensIn,
            tokensOut: $tokensOut
        ) {
            conversationId
            turnSeq
            chunk
            done
        }
    }
    """

    payload = json.dumps({
        "query": mutation,
        "variables": {
            "conversationId": conversation_id,
            "turnSeq": turn_seq,
            "chunk": chunk,
            "done": done,
            "tokensIn": tokens_in,
            "tokensOut": tokens_out,
        },
    }).encode("utf-8")

    session = boto3.Session()
    credentials = session.get_credentials().get_frozen_credentials()

    request = AWSRequest(
        method="POST",
        url=APPSYNC_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
    )
    SigV4Auth(credentials, "appsync", session.region_name).add_auth(request)

    req = urllib.request.Request(
        APPSYNC_ENDPOINT,
        data=payload,
        headers=dict(request.headers),
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        resp_body = resp.read().decode("utf-8")
        if '"errors"' in resp_body:
            logger.error("AppSync publish returned errors: %s", resp_body[:500])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        logger.error("AppSync publish HTTP %d: %s", e.code, body[:500])
    except Exception:
        logger.exception("Failed to publish chunk to AppSync")


def handler(event: dict, context) -> dict:
    """Async Lambda: streams Bedrock response and publishes chunks to AppSync.

    Invoked asynchronously by chat_dispatch. Event contains:
    {user_id, paper_id, conv_id, message, turn_seq}
    """
    user_id = event["user_id"]
    paper_id = event["paper_id"]
    conv_id = event["conv_id"]
    message = event["message"]
    seq = event["turn_seq"]

    # Set up resources
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)
    s3_client = boto3.client("s3")

    # 1. Get conversation to find S3 key
    conv = db.get_conversation_by_paper(table, user_id, paper_id)
    if conv is None:
        _publish_chunk(conv_id, seq, "[Error: conversation not found]", True)
        return {"status": "error"}

    full_text_s3_key = conv.get("full_text_s3_key", "")

    # 2. Try RAG retrieval first, fall back to full-text stuffing
    retrieved_context = None

    if db.is_paper_embedded(table, paper_id):
        try:
            from backend.shared.embeddings import embed_text
            from backend.shared.vectors import query_vectors, get_chunk_texts

            user_paper_ids = db.list_user_paper_ids(table, user_id)
            query_embedding = embed_text(message)
            chunks = query_vectors(query_embedding, paper_ids=user_paper_ids, top_k=10)

            if chunks:
                hit_paper_ids = set(c.get("metadata", {}).get("paper_id", "") for c in chunks)
                chunk_texts = get_chunk_texts(hit_paper_ids)
                retrieved_context = _format_retrieved_chunks(chunks, chunk_texts)
                logger.info("RAG retrieval: %d chunks from %d papers", len(chunks), len(hit_paper_ids))
        except Exception:
            logger.warning("RAG retrieval failed — falling back to full text")

    # Fallback: full-text stuffing
    paper_text = None
    if not retrieved_context:
        paper_text = _read_s3_text(s3_client, BUCKET_NAME, full_text_s3_key)
        if not paper_text:
            _publish_chunk(conv_id, seq, "[Error: paper not found in S3]", True)
            return {"status": "error"}

    # 3. Read existing turns (excluding the current one just created) + profile
    turns = db.get_conversation_turns(table, user_id, conv_id)
    turns = [t for t in turns if int(t.get("seq", 0)) < seq]
    profile = db.get_full_profile(table, user_id)

    # 4. Build LLM context
    if retrieved_context:
        system_prompt = _build_system_prompt_with_retrieval(retrieved_context, profile)
    else:
        system_prompt = _build_system_prompt(paper_text, profile)
    llm_messages = _build_messages(turns, message)

    # 7. Call Bedrock streaming and publish chunks
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        config=Config(read_timeout=300, retries={"max_attempts": 2}),
    )

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.3,
        "system": system_prompt,
        "messages": llm_messages,
    }

    response_chunks: list[str] = []
    tokens_in = 0
    tokens_out = 0

    try:
        response = client.invoke_model_with_response_stream(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )

        for event_data in response.get("body", []):
            chunk = json.loads(event_data.get("chunk", {}).get("bytes", b"{}"))
            event_type = chunk.get("type", "")

            if event_type == "content_block_delta":
                delta = chunk.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    response_chunks.append(text)
                    _publish_chunk(conv_id, seq, text, False)

            elif event_type == "message_delta":
                usage = chunk.get("usage", {})
                tokens_out = usage.get("output_tokens", 0)

            elif event_type == "message_start":
                usage = chunk.get("message", {}).get("usage", {})
                tokens_in = usage.get("input_tokens", 0)

        # Publish done signal
        _publish_chunk(conv_id, seq, "", True, tokens_in, tokens_out)

    except Exception:
        logger.exception("Bedrock streaming failed")
        _publish_chunk(conv_id, seq, "[Error: LLM streaming failed]", True)
        return {"conversationId": conv_id, "turnSeq": seq, "status": "error:llm_failed"}

    # 8. Update turn with full response
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

    return {"conversationId": conv_id, "turnSeq": seq, "status": "ok"}

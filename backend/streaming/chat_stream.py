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

from backend.shared import db, metrics  # metrics.emit never raises
from backend.streaming.chat import (
    _build_system_prompt,
    _build_system_prompt_with_retrieval,
    _build_messages,
    _read_s3_text,
    _format_retrieved_chunks,
    _format_card_context,
    _format_summaries,
    SYSTEM_PROMPT,
)
from boto3.dynamodb.conditions import Key

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
            metrics.emit("PublishChunkFailed", 1)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        logger.error("AppSync publish HTTP %d: %s", e.code, body[:500])
        metrics.emit("PublishChunkFailed", 1)
    except Exception:
        logger.exception("Failed to publish chunk to AppSync")
        metrics.emit("PublishChunkFailed", 1)


def handler(event: dict, context) -> dict:
    """Async Lambda: streams Bedrock response and publishes chunks to AppSync.

    Invoked asynchronously by chat_dispatch. Event contains:
    {user_id, paper_id, conv_id, message, turn_seq, scope?}
    """
    user_id = event["user_id"]
    workspace_id = event.get("workspace_id", "")
    paper_id = event.get("paper_id", "")
    conv_id = event["conv_id"]
    message = event["message"]
    seq = event["turn_seq"]
    scope = event.get("scope", "paper")

    # Set up resources
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)
    s3_client = boto3.client("s3")

    if not workspace_id:
        # Fall back to active workspace if dispatcher didn't set one (legacy path)
        workspace_id = db.get_active_workspace(table, user_id) or ""

    full_text_s3_key = ""

    # 1. For paper-scoped chats, get the conversation and S3 key
    if scope == "paper" and paper_id:
        conv = db.get_conversation_by_paper(table, user_id, workspace_id, paper_id)
        if conv is None:
            _publish_chunk(conv_id, seq, "[Error: conversation not found]", True)
            return {"status": "error"}
        full_text_s3_key = conv.get("full_text_s3_key", "")

    # 2. Try RAG retrieval first, fall back to full-text stuffing
    retrieved_context = None

    # RAG retrieval — always try for research scope, or for embedded papers
    use_rag = scope == "research" or (paper_id and db.is_paper_embedded(table, paper_id))
    if use_rag:
        try:
            from backend.shared.embeddings import embed_text
            from backend.shared.vectors import query_vectors, get_chunk_texts

            user_paper_ids = db.list_user_paper_ids(table, user_id, workspace_id)
            query_embedding = embed_text(message)
            chunks = query_vectors(query_embedding, paper_ids=user_paper_ids, top_k=10)

            if chunks:
                hit_paper_ids = set(c.get("metadata", {}).get("paper_id", "") for c in chunks)
                chunk_texts = get_chunk_texts(hit_paper_ids)
                retrieved_context = _format_retrieved_chunks(chunks, chunk_texts)
                logger.info("RAG retrieval: %d chunks from %d papers", len(chunks), len(hit_paper_ids))
        except Exception:
            logger.warning("RAG retrieval failed — falling back to full text")

    # Fallback: full-text stuffing (only for paper-scoped chats)
    paper_text = None
    if not retrieved_context and full_text_s3_key:
        paper_text = _read_s3_text(s3_client, BUCKET_NAME, full_text_s3_key)
        if not paper_text and scope == "paper":
            _publish_chunk(conv_id, seq, "[Error: paper not found in S3]", True)
            return {"status": "error"}

    # 3. Read existing turns (excluding the current one just created) + profile
    turns = db.get_conversation_turns(table, user_id, workspace_id, conv_id)
    turns = [t for t in turns if int(t.get("seq", 0)) < seq]
    profile = db.get_full_profile(table, user_id, workspace_id)

    # 3b. Load card details for the current paper (glossary, digest, etc.)
    card = db.get_feed_card_by_paper(table, user_id, workspace_id, paper_id) if paper_id else None
    card_context = _format_card_context(card) if card else ""

    # 3c. Load research context: tags + pinned insights across library
    research_context = _build_research_context(table, user_id, workspace_id)

    # 4. Build LLM context
    if retrieved_context:
        system_prompt = _build_system_prompt_with_retrieval(retrieved_context, profile, card_context)
    else:
        system_prompt = _build_system_prompt(paper_text, profile)
        if card_context:
            system_prompt += f"\n\n<card_details>\n{card_context}\n</card_details>"
    if research_context:
        system_prompt += f"\n\n<research_context>\n{research_context}\n</research_context>"
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

        # Publish done signal with full response for client confirmation
        full_response = "".join(response_chunks)
        _publish_chunk(conv_id, seq, full_response, True, tokens_in, tokens_out)
        metrics.emit("ChatStreamCompleted", 1)

    except Exception:
        logger.exception("Bedrock streaming failed")
        _publish_chunk(conv_id, seq, "[Error: LLM streaming failed]", True)
        metrics.emit("ChatStreamFailed", 1)
        return {"conversationId": conv_id, "turnSeq": seq, "status": "error:llm_failed"}

    # 8. Update turn with full response
    full_response = "".join(response_chunks)
    response_ts = _now_iso()
    db.update_turn_response(
        table, user_id, workspace_id, conv_id, seq,
        response=full_response,
        response_ts=response_ts,
        citations=[],
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )

    # Auto-title: generate a title from the first message
    if seq == 1 and message:
        try:
            from backend.shared.llm import call_llm
            title = call_llm(
                system="Generate a short title (max 6 words) for a conversation that starts with this message. Return ONLY the title, no quotes, no explanation.",
                user_message=message,
                model_id="us.anthropic.claude-haiku-4-5-20251001",
                max_tokens=30,
                temperature=0.3,
            )
            if title and len(title.strip()) > 0:
                db.update_conversation_title(
                    table, user_id, workspace_id, conv_id, title.strip()
                )
        except Exception:
            pass

    return {"conversationId": conv_id, "turnSeq": seq, "status": "ok"}


def _build_research_context(table, user_id: str, workspace_id: str) -> str:
    """Build research context from tagged papers + pinned insights across library."""
    # Get all feed cards with tags (workspace-scoped)
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(db._feed_pk(user_id, workspace_id))
            & Key("SK").begins_with("CARD#")
        ),
    )
    cards = resp.get("Items", [])
    core_cards = [c for c in cards if c.get("relevance") == "core"]

    if not core_cards:
        # Get pinned insights even without tagged papers
        pass

    parts = []

    # Tag structure
    if core_cards:
        tag_map: dict[str, list[str]] = {}
        for card in core_cards:
            for tag in card.get("tags", []):
                if tag not in tag_map:
                    tag_map[tag] = []
                tag_map[tag].append(card.get("hook", "")[:80])

        if tag_map:
            parts.append("RESEARCH TAGS:")
            for tag, hooks in tag_map.items():
                parts.append(f"  [{tag}] ({len(hooks)} papers)")
                for hook in hooks[:3]:
                    parts.append(f"    - {hook}")

    # Pinned insights across all conversations (workspace-scoped)
    conv_resp = table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("gsi1pk").eq(
            db._gsi_user_scope(user_id, workspace_id)
        ),
    )
    convs = conv_resp.get("Items", [])

    pinned_parts = []
    for conv in convs:
        conv_id = conv.get("conv_id", "")
        turns_resp = table.query(
            KeyConditionExpression=(
                Key("PK").eq(db._conv_pk(user_id, workspace_id, conv_id))
                & Key("SK").begins_with("TURN#")
            ),
            FilterExpression="pinned = :t",
            ExpressionAttributeValues={":t": True},
        )
        for turn in turns_resp.get("Items", []):
            question = turn.get("request", "")[:100]
            answer = (turn.get("response") or "")[:200]
            pin_note = turn.get("pin_note", "")
            if answer:
                entry = f"  Q: {question}\n  A: {answer}..."
                if pin_note:
                    entry += f"\n  Note: {pin_note}"
                pinned_parts.append(entry)

    if pinned_parts:
        parts.append("\nPINNED INSIGHTS (key takeaways the user marked across their library):")
        for p in pinned_parts[:10]:
            parts.append(p)

    return "\n".join(parts) if parts else ""

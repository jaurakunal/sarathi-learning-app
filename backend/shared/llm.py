"""Shared LLM client using AWS Bedrock (no API keys needed). v2"""

from __future__ import annotations

import json
import logging
from typing import Generator, Optional

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
DEFAULT_REGION = "us-east-1"


def call_llm(
    system: str,
    user_message: str,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    region: Optional[str] = None,
) -> Optional[str]:
    """Call an LLM via AWS Bedrock and return the text response.

    Args:
        system: System prompt.
        user_message: User message content.
        model_id: Bedrock model ID (defaults to Claude Sonnet).
        max_tokens: Max output tokens.
        temperature: Sampling temperature.
        region: AWS region (defaults to us-east-1).

    Returns:
        The assistant's text response, or None if the call fails.
    """
    client = boto3.client(
        "bedrock-runtime",
        region_name=region or DEFAULT_REGION,
        config=Config(read_timeout=300, retries={"max_attempts": 2}),
    )

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [
            {"role": "user", "content": user_message}
        ],
    }

    try:
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )

        response_body = json.loads(response["body"].read())
        content = response_body.get("content", [])

        if content and content[0].get("type") == "text":
            return content[0]["text"]

        logger.warning("Bedrock response had no text content: %s", response_body)
        return None

    except Exception:
        logger.exception("Bedrock LLM call failed (model=%s)", model_id)
        return None


def stream_llm(
    system: str,
    messages: list[dict],
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    region: Optional[str] = None,
) -> Generator[str, None, Optional[dict]]:
    """Stream LLM response via Bedrock. Yields text chunks.

    Args:
        system: System prompt.
        messages: Full message history [{role, content}, ...].
        model_id: Bedrock model ID.
        max_tokens: Max output tokens.
        temperature: Sampling temperature.
        region: AWS region.

    Yields:
        Text chunks as they arrive.

    Returns:
        Usage metadata dict {tokens_in, tokens_out} after stream ends,
        or None on failure.
    """
    client = boto3.client(
        "bedrock-runtime",
        region_name=region or DEFAULT_REGION,
        config=Config(read_timeout=300, retries={"max_attempts": 1}),
    )

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": messages,
    }

    try:
        response = client.invoke_model_with_response_stream(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
    except Exception:
        logger.exception("Bedrock stream call failed (model=%s)", model_id)
        return None

    tokens_in = 0
    tokens_out = 0

    for event in response.get("body", []):
        chunk = json.loads(event.get("chunk", {}).get("bytes", b"{}"))
        event_type = chunk.get("type", "")

        if event_type == "content_block_delta":
            delta = chunk.get("delta", {})
            if delta.get("type") == "text_delta":
                yield delta.get("text", "")

        elif event_type == "message_delta":
            usage = chunk.get("usage", {})
            tokens_out = usage.get("output_tokens", 0)

        elif event_type == "message_start":
            usage = chunk.get("message", {}).get("usage", {})
            tokens_in = usage.get("input_tokens", 0)

    return {"tokens_in": tokens_in, "tokens_out": tokens_out}

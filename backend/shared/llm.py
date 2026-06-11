"""Shared LLM client using AWS Bedrock (no API keys needed)."""

from __future__ import annotations

import json
import logging
from typing import Optional

import boto3

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

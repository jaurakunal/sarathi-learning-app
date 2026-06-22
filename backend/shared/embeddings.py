"""Embedding helper using Amazon Titan Embeddings v2 via Bedrock."""

from __future__ import annotations

import json
import logging
from typing import Optional

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "amazon.titan-embed-text-v2:0"
DEFAULT_REGION = "us-east-1"


def embed_text(
    text: str,
    model_id: str = DEFAULT_MODEL_ID,
    region: Optional[str] = None,
) -> list[float]:
    """Embed a single text using Titan Embeddings v2 via Bedrock.

    Args:
        text: The text to embed (max ~8K tokens for Titan v2).
        model_id: Bedrock model ID for embeddings.
        region: AWS region.

    Returns:
        List of floats (1024-dimensional embedding vector).

    Raises:
        Exception if the Bedrock call fails.
    """
    client = boto3.client(
        "bedrock-runtime",
        region_name=region or DEFAULT_REGION,
        config=Config(read_timeout=30, retries={"max_attempts": 2}),
    )

    body = json.dumps({
        "inputText": text[:20000],  # Safety truncation (~8K tokens ≈ ~20K chars)
    })

    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    response_body = json.loads(response["body"].read())
    embedding = response_body.get("embedding")

    if not embedding:
        raise ValueError(f"No embedding returned from {model_id}")

    return embedding


def embed_batch(texts: list[str], model_id: str = DEFAULT_MODEL_ID) -> list[list[float]]:
    """Embed multiple texts sequentially.

    Titan v2 doesn't support native batching, so this calls embed_text
    for each text. At 18 papers × 6 sections = ~108 calls, this takes
    ~30 seconds (acceptable in the Fargate Digest step).
    """
    results = []
    for text in texts:
        try:
            results.append(embed_text(text, model_id=model_id))
        except Exception:
            logger.warning("Failed to embed text (len=%d), using zero vector", len(text))
            results.append([0.0] * 1024)
    return results

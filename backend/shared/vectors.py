"""S3 Vectors wrapper for storing and querying paper section embeddings."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

def _get_vector_bucket_name():
    return os.environ.get("VECTOR_BUCKET_NAME", "")

def _get_vector_index_name():
    return os.environ.get("VECTOR_INDEX_NAME", "paper-sections")


def _get_client():
    """Get the S3 Vectors client."""
    return boto3.client("s3vectors", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


def put_vectors(chunks: list[dict], embeddings: list[list[float]]) -> int:
    """Store paper section embeddings in S3 Vectors.

    Args:
        chunks: List of {chunk_text, section_name, paper_id, paper_title}
        embeddings: Corresponding embedding vectors (1024-dim each)

    Returns:
        Number of vectors successfully stored.
    """
    VECTOR_BUCKET_NAME = _get_vector_bucket_name()
    VECTOR_INDEX_NAME = _get_vector_index_name()
    if not VECTOR_BUCKET_NAME:
        logger.warning("VECTOR_BUCKET_NAME not set — skipping vector storage")
        return 0

    client = _get_client()
    vectors = []

    chunk_texts = {}
    for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        key = f"{chunk['paper_id']}:{chunk['section_name']}:{idx}"
        vectors.append({
            "key": key,
            "data": {"float32": embedding},
            "metadata": {
                "paper_id": chunk["paper_id"],
                "paper_title": chunk["paper_title"],
                "section_name": chunk["section_name"],
            },
        })
        chunk_texts[key] = chunk["chunk_text"]

    if not vectors:
        return 0

    try:
        client.put_vectors(
            vectorBucketName=VECTOR_BUCKET_NAME,
            indexName=VECTOR_INDEX_NAME,
            vectors=vectors,
        )
        _store_chunk_texts(chunks[0]["paper_id"], chunk_texts)
        logger.info("Stored %d vectors for paper %s", len(vectors), chunks[0]["paper_id"])
        return len(vectors)
    except Exception:
        logger.exception("Failed to store vectors in S3 Vectors")
        return 0


def _store_chunk_texts(paper_id: str, chunk_texts: dict[str, str]) -> None:
    """Store chunk texts in S3 for retrieval at query time."""
    bucket = os.environ.get("BUCKET_NAME", "")
    if not bucket:
        return
    s3 = boto3.client("s3")
    key = f"vectors/{paper_id}/chunks.json"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(chunk_texts),
        ContentType="application/json",
    )


def get_chunk_texts(paper_ids: set[str]) -> dict[str, str]:
    """Load chunk texts from S3 for the given papers. Returns {vector_key: text}."""
    bucket = os.environ.get("BUCKET_NAME", "")
    if not bucket:
        return {}
    s3 = boto3.client("s3")
    all_texts = {}
    for paper_id in paper_ids:
        key = f"vectors/{paper_id}/chunks.json"
        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            texts = json.loads(resp["Body"].read().decode("utf-8"))
            all_texts.update(texts)
        except Exception:
            pass
    return all_texts


def query_vectors(
    query_embedding: list[float],
    paper_ids: Optional[set[str]] = None,
    top_k: int = 10,
    return_distance: bool = False,
) -> list[dict]:
    """Query S3 Vectors for chunks similar to the query embedding.

    Args:
        query_embedding: The embedded query vector (1024-dim).
        paper_ids: If provided, filter to only these papers (tenant isolation).
        top_k: Number of results to return.
        return_distance: If True, each result also carries its cosine ``distance``.

    Returns:
        List of {key, metadata, score} dicts, sorted by similarity.
    """
    VECTOR_BUCKET_NAME = _get_vector_bucket_name()
    VECTOR_INDEX_NAME = _get_vector_index_name()
    if not VECTOR_BUCKET_NAME:
        logger.warning("VECTOR_BUCKET_NAME not set — cannot query vectors")
        return []

    client = _get_client()

    kwargs = {
        "vectorBucketName": VECTOR_BUCKET_NAME,
        "indexName": VECTOR_INDEX_NAME,
        "queryVector": {"float32": query_embedding},
        "topK": top_k,
        "returnMetadata": True,
    }
    if return_distance:
        kwargs["returnDistance"] = True

    if paper_ids:
        kwargs["filter"] = {"$or": [{"paper_id": pid} for pid in paper_ids]}

    try:
        response = client.query_vectors(**kwargs)
        results = response.get("vectors", [])
        logger.info("Vector query returned %d results", len(results))
        return results
    except Exception:
        logger.exception("Failed to query S3 Vectors")
        return []


def delete_vectors(paper_id: str, section_names: list[str]) -> None:
    """Delete vectors for a paper (used if re-embedding is needed)."""
    VECTOR_BUCKET_NAME = _get_vector_bucket_name()
    VECTOR_INDEX_NAME = _get_vector_index_name()
    if not VECTOR_BUCKET_NAME:
        return

    client = _get_client()
    keys = [f"{paper_id}:{name}" for name in section_names]

    try:
        client.delete_vectors(
            vectorBucketName=VECTOR_BUCKET_NAME,
            indexName=VECTOR_INDEX_NAME,
            keys=keys,
        )
    except Exception:
        logger.exception("Failed to delete vectors for paper %s", paper_id)

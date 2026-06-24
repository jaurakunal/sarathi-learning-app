"""Unit tests for backend.shared.vectors — S3 Vectors wrapper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.shared import vectors


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_chunks():
    return [
        {
            "chunk_text": "This is chunk 0",
            "section_name": "introduction",
            "paper_id": "paper-001",
            "paper_title": "Test Paper",
        },
        {
            "chunk_text": "This is chunk 1",
            "section_name": "method",
            "paper_id": "paper-001",
            "paper_title": "Test Paper",
        },
    ]


@pytest.fixture
def sample_embeddings():
    return [[0.1] * 1024, [0.2] * 1024]


# ---------------------------------------------------------------------------
# put_vectors
# ---------------------------------------------------------------------------


class TestPutVectors:
    @patch("backend.shared.vectors._store_chunk_texts")
    @patch("backend.shared.vectors._get_client")
    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="my-bucket")
    @patch("backend.shared.vectors._get_vector_index_name", return_value="paper-sections")
    def test_stores_vectors_and_chunk_texts(
        self, mock_index, mock_bucket, mock_client_fn, mock_store, sample_chunks, sample_embeddings
    ):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        result = vectors.put_vectors(sample_chunks, sample_embeddings)

        assert result == 2
        mock_client.put_vectors.assert_called_once()
        call_kwargs = mock_client.put_vectors.call_args[1]
        assert call_kwargs["vectorBucketName"] == "my-bucket"
        assert call_kwargs["indexName"] == "paper-sections"
        assert len(call_kwargs["vectors"]) == 2

        # Verify vector keys
        keys = [v["key"] for v in call_kwargs["vectors"]]
        assert keys[0] == "paper-001:introduction:0"
        assert keys[1] == "paper-001:method:1"

        # Verify metadata
        assert call_kwargs["vectors"][0]["metadata"]["paper_id"] == "paper-001"
        assert call_kwargs["vectors"][0]["metadata"]["section_name"] == "introduction"

        # Verify chunk texts stored
        mock_store.assert_called_once()

    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="")
    def test_empty_bucket_name_returns_zero(self, mock_bucket, sample_chunks, sample_embeddings):
        result = vectors.put_vectors(sample_chunks, sample_embeddings)
        assert result == 0

    @patch("backend.shared.vectors._store_chunk_texts")
    @patch("backend.shared.vectors._get_client")
    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="my-bucket")
    @patch("backend.shared.vectors._get_vector_index_name", return_value="paper-sections")
    def test_empty_chunks_returns_zero(self, mock_index, mock_bucket, mock_client_fn, mock_store):
        result = vectors.put_vectors([], [])
        assert result == 0

    @patch("backend.shared.vectors._store_chunk_texts")
    @patch("backend.shared.vectors._get_client")
    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="my-bucket")
    @patch("backend.shared.vectors._get_vector_index_name", return_value="paper-sections")
    def test_exception_returns_zero(
        self, mock_index, mock_bucket, mock_client_fn, mock_store, sample_chunks, sample_embeddings
    ):
        mock_client = MagicMock()
        mock_client.put_vectors.side_effect = Exception("API error")
        mock_client_fn.return_value = mock_client

        result = vectors.put_vectors(sample_chunks, sample_embeddings)
        assert result == 0


# ---------------------------------------------------------------------------
# query_vectors
# ---------------------------------------------------------------------------


class TestQueryVectors:
    @patch("backend.shared.vectors._get_client")
    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="my-bucket")
    @patch("backend.shared.vectors._get_vector_index_name", return_value="paper-sections")
    def test_passes_return_metadata_true(self, mock_index, mock_bucket, mock_client_fn):
        mock_client = MagicMock()
        mock_client.query_vectors.return_value = {"vectors": []}
        mock_client_fn.return_value = mock_client

        vectors.query_vectors([0.1] * 1024)

        call_kwargs = mock_client.query_vectors.call_args[1]
        assert call_kwargs["returnMetadata"] is True

    @patch("backend.shared.vectors._get_client")
    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="my-bucket")
    @patch("backend.shared.vectors._get_vector_index_name", return_value="paper-sections")
    def test_builds_or_filter_from_paper_ids(self, mock_index, mock_bucket, mock_client_fn):
        mock_client = MagicMock()
        mock_client.query_vectors.return_value = {"vectors": []}
        mock_client_fn.return_value = mock_client

        vectors.query_vectors([0.1] * 1024, paper_ids={"p1", "p2"})

        call_kwargs = mock_client.query_vectors.call_args[1]
        assert "$or" in call_kwargs["filter"]
        or_items = call_kwargs["filter"]["$or"]
        paper_id_values = sorted([item["paper_id"] for item in or_items])
        assert paper_id_values == ["p1", "p2"]

    @patch("backend.shared.vectors._get_client")
    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="my-bucket")
    @patch("backend.shared.vectors._get_vector_index_name", return_value="paper-sections")
    def test_returns_vectors_from_response(self, mock_index, mock_bucket, mock_client_fn):
        mock_client = MagicMock()
        mock_client.query_vectors.return_value = {
            "vectors": [{"key": "k1", "score": 0.9}, {"key": "k2", "score": 0.8}]
        }
        mock_client_fn.return_value = mock_client

        result = vectors.query_vectors([0.1] * 1024)
        assert len(result) == 2
        assert result[0]["key"] == "k1"

    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="")
    def test_empty_bucket_returns_empty_list(self, mock_bucket):
        result = vectors.query_vectors([0.1] * 1024)
        assert result == []


# ---------------------------------------------------------------------------
# get_chunk_texts
# ---------------------------------------------------------------------------


class TestGetChunkTexts:
    @patch("backend.shared.vectors.boto3")
    @patch.dict("os.environ", {"BUCKET_NAME": "my-bucket"})
    def test_fetches_chunks_for_each_paper(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        body_mock = MagicMock()
        body_mock.read.return_value = json.dumps({"k1": "text1"}).encode("utf-8")
        mock_s3.get_object.return_value = {"Body": body_mock}

        result = vectors.get_chunk_texts({"paper-001"})

        mock_s3.get_object.assert_called_once_with(
            Bucket="my-bucket", Key="vectors/paper-001/chunks.json"
        )
        assert result == {"k1": "text1"}

    @patch("backend.shared.vectors.boto3")
    @patch.dict("os.environ", {"BUCKET_NAME": "my-bucket"})
    def test_merges_results_from_multiple_papers(self, mock_boto3):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        def get_obj_side_effect(**kwargs):
            key = kwargs["Key"]
            if "paper-001" in key:
                body = MagicMock()
                body.read.return_value = json.dumps({"k1": "text1"}).encode()
                return {"Body": body}
            else:
                body = MagicMock()
                body.read.return_value = json.dumps({"k2": "text2"}).encode()
                return {"Body": body}

        mock_s3.get_object.side_effect = get_obj_side_effect

        result = vectors.get_chunk_texts({"paper-001", "paper-002"})
        assert "k1" in result
        assert "k2" in result

    @patch.dict("os.environ", {"BUCKET_NAME": ""})
    def test_empty_bucket_returns_empty_dict(self):
        result = vectors.get_chunk_texts({"paper-001"})
        assert result == {}


# ---------------------------------------------------------------------------
# delete_vectors
# ---------------------------------------------------------------------------


class TestDeleteVectors:
    @patch("backend.shared.vectors._get_client")
    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="my-bucket")
    @patch("backend.shared.vectors._get_vector_index_name", return_value="paper-sections")
    def test_constructs_keys_correctly(self, mock_index, mock_bucket, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        vectors.delete_vectors("paper-001", ["introduction", "method"])

        mock_client.delete_vectors.assert_called_once()
        call_kwargs = mock_client.delete_vectors.call_args[1]
        assert call_kwargs["vectorBucketName"] == "my-bucket"
        assert call_kwargs["indexName"] == "paper-sections"
        assert sorted(call_kwargs["keys"]) == sorted([
            "paper-001:introduction",
            "paper-001:method",
        ])

    @patch("backend.shared.vectors._get_vector_bucket_name", return_value="")
    def test_empty_bucket_does_nothing(self, mock_bucket):
        # Should not raise
        vectors.delete_vectors("paper-001", ["introduction"])

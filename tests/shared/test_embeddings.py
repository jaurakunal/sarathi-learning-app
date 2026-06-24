"""Unit tests for backend.shared.embeddings — Titan Embeddings v2 wrapper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.shared import embeddings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bedrock_response():
    """Simulates a successful Bedrock invoke_model response."""
    body_content = json.dumps({"embedding": [0.1] * 1024})
    body_mock = MagicMock()
    body_mock.read.return_value = body_content.encode("utf-8")
    return {"body": body_mock}


# ---------------------------------------------------------------------------
# embed_text
# ---------------------------------------------------------------------------


class TestEmbedText:
    @patch("backend.shared.embeddings.boto3")
    def test_returns_embedding_vector(self, mock_boto3, mock_bedrock_response):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = mock_bedrock_response
        mock_boto3.client.return_value = mock_client

        result = embeddings.embed_text("Hello world")

        assert len(result) == 1024
        assert result[0] == 0.1

    @patch("backend.shared.embeddings.boto3")
    def test_sends_correct_model_id(self, mock_boto3, mock_bedrock_response):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = mock_bedrock_response
        mock_boto3.client.return_value = mock_client

        embeddings.embed_text("Hello", model_id="custom-model")

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "custom-model"

    @patch("backend.shared.embeddings.boto3")
    def test_sends_correct_body_format(self, mock_boto3, mock_bedrock_response):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = mock_bedrock_response
        mock_boto3.client.return_value = mock_client

        embeddings.embed_text("Test input text")

        call_kwargs = mock_client.invoke_model.call_args[1]
        body = json.loads(call_kwargs["body"])
        assert body["inputText"] == "Test input text"
        assert call_kwargs["contentType"] == "application/json"
        assert call_kwargs["accept"] == "application/json"

    @patch("backend.shared.embeddings.boto3")
    def test_truncates_long_text(self, mock_boto3, mock_bedrock_response):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = mock_bedrock_response
        mock_boto3.client.return_value = mock_client

        long_text = "x" * 30000
        embeddings.embed_text(long_text)

        call_kwargs = mock_client.invoke_model.call_args[1]
        body = json.loads(call_kwargs["body"])
        assert len(body["inputText"]) == 20000

    @patch("backend.shared.embeddings.boto3")
    def test_raises_on_empty_embedding(self, mock_boto3):
        body_content = json.dumps({"embedding": None})
        body_mock = MagicMock()
        body_mock.read.return_value = body_content.encode("utf-8")
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": body_mock}
        mock_boto3.client.return_value = mock_client

        with pytest.raises(ValueError, match="No embedding returned"):
            embeddings.embed_text("test")

    @patch("backend.shared.embeddings.boto3")
    def test_uses_default_region(self, mock_boto3, mock_bedrock_response):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = mock_bedrock_response
        mock_boto3.client.return_value = mock_client

        embeddings.embed_text("test")

        mock_boto3.client.assert_called_once()
        call_args = mock_boto3.client.call_args
        assert call_args[1]["region_name"] == "us-east-1"


# ---------------------------------------------------------------------------
# embed_batch
# ---------------------------------------------------------------------------


class TestEmbedBatch:
    @patch("backend.shared.embeddings.embed_text")
    def test_calls_embed_text_for_each_item(self, mock_embed):
        mock_embed.return_value = [0.1] * 1024

        result = embeddings.embed_batch(["text1", "text2", "text3"])

        assert mock_embed.call_count == 3
        assert len(result) == 3
        assert len(result[0]) == 1024

    @patch("backend.shared.embeddings.embed_text")
    def test_returns_zero_vector_on_failure(self, mock_embed):
        mock_embed.side_effect = [
            [0.1] * 1024,
            Exception("API error"),
            [0.3] * 1024,
        ]

        result = embeddings.embed_batch(["a", "b", "c"])

        assert len(result) == 3
        assert result[0] == [0.1] * 1024
        assert result[1] == [0.0] * 1024  # Zero vector fallback
        assert result[2] == [0.3] * 1024

    @patch("backend.shared.embeddings.embed_text")
    def test_empty_list_returns_empty(self, mock_embed):
        result = embeddings.embed_batch([])
        assert result == []
        mock_embed.assert_not_called()

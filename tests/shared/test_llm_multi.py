"""Unit tests for call_llm_multi in backend.shared.llm.

Tests cover:
- Passes messages list to Bedrock correctly
- Returns text on success
- Returns None on error
- Uses correct default model and region
"""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from backend.shared.llm import call_llm_multi


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_messages():
    return [
        {"role": "user", "content": "What is episodic memory?"},
        {"role": "assistant", "content": "Episodic memory is memory of specific events."},
        {"role": "user", "content": "How does it relate to AI agents?"},
    ]


@pytest.fixture
def sample_system():
    return "You are a research assistant."


@pytest.fixture
def mock_bedrock_response():
    """A mock Bedrock response with successful text content."""
    response_body = {
        "content": [
            {"type": "text", "text": "Episodic memory in AI agents refers to..."}
        ],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    body_stream = BytesIO(json.dumps(response_body).encode())
    return {"body": body_stream}


@pytest.fixture
def mock_bedrock_empty_response():
    """A mock Bedrock response with no text content."""
    response_body = {"content": [], "usage": {"input_tokens": 10, "output_tokens": 0}}
    body_stream = BytesIO(json.dumps(response_body).encode())
    return {"body": body_stream}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCallLlmMulti:
    @patch("backend.shared.llm.boto3")
    def test_returns_text_on_success(self, mock_boto3, sample_system, sample_messages, mock_bedrock_response):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = mock_bedrock_response

        result = call_llm_multi(system=sample_system, messages=sample_messages)

        assert result == "Episodic memory in AI agents refers to..."

    @patch("backend.shared.llm.boto3")
    def test_passes_messages_to_bedrock(self, mock_boto3, sample_system, sample_messages):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        response_body = {"content": [{"type": "text", "text": "OK"}]}
        mock_client.invoke_model.return_value = {"body": BytesIO(json.dumps(response_body).encode())}

        call_llm_multi(system=sample_system, messages=sample_messages)

        mock_client.invoke_model.assert_called_once()
        call_kwargs = mock_client.invoke_model.call_args[1]
        request_body = json.loads(call_kwargs["body"])
        assert request_body["messages"] == sample_messages
        assert request_body["system"] == sample_system

    @patch("backend.shared.llm.boto3")
    def test_uses_default_model_id(self, mock_boto3, sample_system, sample_messages):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        response_body = {"content": [{"type": "text", "text": "response"}]}
        mock_client.invoke_model.return_value = {"body": BytesIO(json.dumps(response_body).encode())}

        call_llm_multi(system=sample_system, messages=sample_messages)

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "us.anthropic.claude-sonnet-4-6"

    @patch("backend.shared.llm.boto3")
    def test_uses_custom_model_id(self, mock_boto3, sample_system, sample_messages):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        response_body = {"content": [{"type": "text", "text": "response"}]}
        mock_client.invoke_model.return_value = {"body": BytesIO(json.dumps(response_body).encode())}

        call_llm_multi(
            system=sample_system,
            messages=sample_messages,
            model_id="us.anthropic.claude-haiku-4",
        )

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "us.anthropic.claude-haiku-4"

    @patch("backend.shared.llm.boto3")
    def test_passes_max_tokens_and_temperature(self, mock_boto3, sample_system, sample_messages):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        response_body = {"content": [{"type": "text", "text": "x"}]}
        mock_client.invoke_model.return_value = {"body": BytesIO(json.dumps(response_body).encode())}

        call_llm_multi(
            system=sample_system,
            messages=sample_messages,
            max_tokens=2000,
            temperature=0.3,
        )

        call_kwargs = mock_client.invoke_model.call_args[1]
        request_body = json.loads(call_kwargs["body"])
        assert request_body["max_tokens"] == 2000
        assert request_body["temperature"] == 0.3

    @patch("backend.shared.llm.boto3")
    def test_returns_none_on_exception(self, mock_boto3, sample_system, sample_messages):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.side_effect = Exception("ServiceUnavailable")

        result = call_llm_multi(system=sample_system, messages=sample_messages)

        assert result is None

    @patch("backend.shared.llm.boto3")
    def test_returns_none_on_empty_content(self, mock_boto3, sample_system, sample_messages, mock_bedrock_empty_response):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = mock_bedrock_empty_response

        result = call_llm_multi(system=sample_system, messages=sample_messages)

        assert result is None

    @patch("backend.shared.llm.boto3")
    def test_uses_default_region(self, mock_boto3, sample_system, sample_messages):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        response_body = {"content": [{"type": "text", "text": "ok"}]}
        mock_client.invoke_model.return_value = {"body": BytesIO(json.dumps(response_body).encode())}

        call_llm_multi(system=sample_system, messages=sample_messages)

        mock_boto3.client.assert_called_once()
        call_args = mock_boto3.client.call_args
        assert call_args[1]["region_name"] == "us-east-1"

    @patch("backend.shared.llm.boto3")
    def test_uses_custom_region(self, mock_boto3, sample_system, sample_messages):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        response_body = {"content": [{"type": "text", "text": "ok"}]}
        mock_client.invoke_model.return_value = {"body": BytesIO(json.dumps(response_body).encode())}

        call_llm_multi(system=sample_system, messages=sample_messages, region="eu-west-1")

        call_args = mock_boto3.client.call_args
        assert call_args[1]["region_name"] == "eu-west-1"

    @patch("backend.shared.llm.boto3")
    def test_includes_anthropic_version(self, mock_boto3, sample_system, sample_messages):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        response_body = {"content": [{"type": "text", "text": "hi"}]}
        mock_client.invoke_model.return_value = {"body": BytesIO(json.dumps(response_body).encode())}

        call_llm_multi(system=sample_system, messages=sample_messages)

        call_kwargs = mock_client.invoke_model.call_args[1]
        request_body = json.loads(call_kwargs["body"])
        assert request_body["anthropic_version"] == "bedrock-2023-05-31"

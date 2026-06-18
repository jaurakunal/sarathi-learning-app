"""Tests for the streaming chat handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

from backend.streaming.chat import (
    handler,
    _build_messages,
    _format_summaries,
    _extract_sub_from_jwt,
    _sse_event,
)


def _make_event(body=None, token="eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0LXVzZXItMTIzIiwiaXNzIjoiY29nbml0byJ9.sig"):
    """Build a minimal Lambda Function URL event."""
    return {
        "requestContext": {"authorizer": {}},
        "headers": {"authorization": token},
        "body": json.dumps(body) if body else None,
    }


class TestBuildMessages:
    def test_first_message_includes_paper_context(self):
        msgs = _build_messages([], "What is reflection?", "Paper text here", "Summary here")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "<paper>" in msgs[0]["content"]
        assert "Paper text here" in msgs[0]["content"]
        assert "Summary here" in msgs[0]["content"]
        assert "What is reflection?" in msgs[0]["content"]

    def test_subsequent_messages_no_paper_context(self):
        turns = [
            {"request": "First question", "response": "First answer"},
        ]
        msgs = _build_messages(turns, "Follow-up", "Paper text", "Summaries")
        assert len(msgs) == 3  # prev user, prev assistant, new user
        assert msgs[0] == {"role": "user", "content": "First question"}
        assert msgs[1] == {"role": "assistant", "content": "First answer"}
        assert msgs[2] == {"role": "user", "content": "Follow-up"}
        assert "<paper>" not in msgs[2]["content"]

    def test_skips_turns_with_no_response(self):
        turns = [
            {"request": "Question", "response": None},
        ]
        msgs = _build_messages(turns, "New question", "Paper", "")
        # Turn with no response: request is included, but no assistant message
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "Question"}
        assert msgs[1] == {"role": "user", "content": "New question"}

    def test_empty_summaries_not_included(self):
        msgs = _build_messages([], "Question", "Paper text", "")
        assert "<user_context>" not in msgs[0]["content"]


class TestFormatSummaries:
    def test_formats_multiple_summaries(self):
        summaries = [
            {"SK": "SUMMARY#7_day", "tier": "7_day", "content": "Read 2 papers."},
            {"SK": "SUMMARY#yesterday", "tier": "yesterday", "content": "Engaged with MemGPT."},
        ]
        result = _format_summaries(summaries)
        assert "[yesterday] Engaged with MemGPT." in result
        assert "[7_day] Read 2 papers." in result

    def test_empty_summaries(self):
        assert _format_summaries([]) == ""

    def test_skips_empty_content(self):
        summaries = [{"SK": "SUMMARY#month", "tier": "month", "content": ""}]
        assert _format_summaries(summaries) == ""


class TestExtractSubFromJwt:
    def test_extracts_sub_from_valid_jwt(self):
        import base64
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "user-abc"}).encode()).rstrip(b"=").decode()
        token = f"header.{payload}.signature"
        assert _extract_sub_from_jwt(token) == "user-abc"

    def test_returns_empty_for_invalid_token(self):
        assert _extract_sub_from_jwt("not-a-jwt") == ""

    def test_returns_empty_for_missing_sub(self):
        import base64
        payload = base64.urlsafe_b64encode(json.dumps({"iss": "cognito"}).encode()).rstrip(b"=").decode()
        token = f"header.{payload}.signature"
        assert _extract_sub_from_jwt(token) == ""


class TestSseEvent:
    def test_formats_correctly(self):
        result = _sse_event({"type": "chunk", "text": "hello"})
        assert result == 'data: {"type": "chunk", "text": "hello"}\n\n'


class TestHandler:
    @patch("backend.streaming.chat.boto3")
    @patch("backend.streaming.chat.db")
    def test_missing_body_returns_400(self, mock_db, mock_boto3):
        event = _make_event(body=None)
        result = handler(event, None)
        assert result["statusCode"] == 400

    @patch("backend.streaming.chat.boto3")
    @patch("backend.streaming.chat.db")
    def test_missing_paper_id_returns_400(self, mock_db, mock_boto3):
        event = _make_event(body={"message": "hi"})
        result = handler(event, None)
        assert result["statusCode"] == 400

    @patch("backend.streaming.chat.boto3")
    @patch("backend.streaming.chat.db")
    def test_missing_message_returns_400(self, mock_db, mock_boto3):
        event = _make_event(body={"paper_id": "abc"})
        result = handler(event, None)
        assert result["statusCode"] == 400

    def test_no_auth_returns_401(self):
        event = {
            "requestContext": {"authorizer": {}},
            "headers": {},
            "body": json.dumps({"paper_id": "abc", "message": "hi"}),
        }
        result = handler(event, None)
        assert result["statusCode"] == 401

    @patch("backend.streaming.chat.stream_llm")
    @patch("backend.streaming.chat.boto3")
    @patch("backend.streaming.chat.db")
    def test_paper_not_in_s3_returns_404(self, mock_db, mock_boto3, mock_stream):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.get_object.side_effect = Exception("NoSuchKey")

        mock_db.get_conversation_by_paper.return_value = None
        mock_db.create_conversation.return_value = {
            "conv_id": "paper1",
            "full_text_s3_key": "users/u/papers/paper1/full_text.txt",
        }

        event = _make_event(body={"paper_id": "paper1", "message": "hi"})
        result = handler(event, None)
        assert result["statusCode"] == 404

    @patch("backend.streaming.chat._read_s3_text")
    @patch("backend.streaming.chat.stream_llm")
    @patch("backend.streaming.chat.boto3")
    @patch("backend.streaming.chat.db")
    def test_successful_stream_returns_sse(self, mock_db, mock_boto3, mock_stream, mock_s3_read):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = MagicMock()
        mock_s3_read.return_value = "Full paper text here"

        mock_db.get_conversation_by_paper.return_value = {
            "conv_id": "paper1",
            "full_text_s3_key": "key",
        }
        mock_db.get_conversation_turns.return_value = []
        mock_db.get_full_profile.return_value = {"summaries": []}

        def fake_stream(*args, **kwargs):
            yield "Hello "
            yield "world"
            return {"tokens_in": 100, "tokens_out": 5}

        mock_stream.return_value = fake_stream()

        event = _make_event(body={"paper_id": "paper1", "message": "hi"})
        result = handler(event, None)

        assert result["statusCode"] == 200
        assert result["headers"]["Content-Type"] == "text/event-stream"
        body = result["body"]
        assert '"type": "start"' in body
        assert '"type": "chunk"' in body
        assert "Hello " in body
        assert "world" in body
        assert '"type": "done"' in body

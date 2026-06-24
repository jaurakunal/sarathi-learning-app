"""Tests for the streaming chat handler (AppSync-backed)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

from backend.streaming.chat_stream import handler


def _make_event(user_id="test-user", paper_id="paper1", conv_id="paper1", message="hello", turn_seq=1):
    return {
        "user_id": user_id,
        "paper_id": paper_id,
        "conv_id": conv_id,
        "message": message,
        "turn_seq": turn_seq,
    }


class TestHandler:
    @patch("backend.streaming.chat_stream._publish_chunk")
    @patch("backend.streaming.chat_stream._read_s3_text")
    @patch("backend.streaming.chat_stream.boto3")
    @patch("backend.streaming.chat_stream.db")
    def test_conversation_not_found_publishes_error(self, mock_db, mock_boto3, mock_s3_read, mock_publish):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = None

        result = handler(_make_event(), None)

        assert result["status"] == "error"
        mock_publish.assert_called_once_with("paper1", 1, "[Error: conversation not found]", True)

    @patch("backend.streaming.chat_stream._publish_chunk")
    @patch("backend.streaming.chat_stream._read_s3_text")
    @patch("backend.streaming.chat_stream.boto3")
    @patch("backend.streaming.chat_stream.db")
    def test_paper_not_in_s3_publishes_error(self, mock_db, mock_boto3, mock_s3_read, mock_publish):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = {
            "conv_id": "paper1",
            "full_text_s3_key": "key",
        }
        mock_s3_read.return_value = None

        result = handler(_make_event(), None)

        assert result["status"] == "error"
        mock_publish.assert_called_once_with("paper1", 1, "[Error: paper not found in S3]", True)

    @patch("backend.streaming.chat_stream._publish_chunk")
    @patch("backend.streaming.chat_stream._read_s3_text")
    @patch("backend.streaming.chat_stream.boto3")
    @patch("backend.streaming.chat_stream.db")
    def test_successful_stream_publishes_chunks_and_done(self, mock_db, mock_boto3, mock_s3_read, mock_publish):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = {
            "conv_id": "paper1",
            "full_text_s3_key": "key",
        }
        mock_db.get_conversation_turns.return_value = []
        mock_db.get_full_profile.return_value = {"summaries": []}
        mock_s3_read.return_value = "Full paper text"

        # Mock Bedrock streaming response
        mock_bedrock = MagicMock()
        mock_boto3.client.return_value = mock_bedrock

        mock_stream = [
            {"chunk": {"bytes": json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 100}}}).encode()}},
            {"chunk": {"bytes": json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}}).encode()}},
            {"chunk": {"bytes": json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}}).encode()}},
            {"chunk": {"bytes": json.dumps({"type": "message_delta", "usage": {"output_tokens": 5}}).encode()}},
        ]
        mock_bedrock.invoke_model_with_response_stream.return_value = {"body": mock_stream}

        result = handler(_make_event(), None)

        assert result["status"] == "ok"
        assert result["conversationId"] == "paper1"
        assert result["turnSeq"] == 1

        # Should publish 2 text chunks + 1 done signal
        assert mock_publish.call_count == 3
        mock_publish.assert_any_call("paper1", 1, "Hello ", False)
        mock_publish.assert_any_call("paper1", 1, "world", False)
        mock_publish.assert_any_call("paper1", 1, "Hello world", True, 100, 5)

    @patch("backend.streaming.chat_stream._publish_chunk")
    @patch("backend.streaming.chat_stream._read_s3_text")
    @patch("backend.streaming.chat_stream.boto3")
    @patch("backend.streaming.chat_stream.db")
    def test_updates_turn_response_in_ddb(self, mock_db, mock_boto3, mock_s3_read, mock_publish):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = {
            "conv_id": "paper1",
            "full_text_s3_key": "key",
        }
        mock_db.get_conversation_turns.return_value = []
        mock_db.get_full_profile.return_value = {"summaries": []}
        mock_s3_read.return_value = "Paper text"

        mock_bedrock = MagicMock()
        mock_boto3.client.return_value = mock_bedrock
        mock_bedrock.invoke_model_with_response_stream.return_value = {"body": [
            {"chunk": {"bytes": json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Answer"}}).encode()}},
            {"chunk": {"bytes": json.dumps({"type": "message_delta", "usage": {"output_tokens": 2}}).encode()}},
        ]}

        handler(_make_event(), None)

        mock_db.update_turn_response.assert_called_once()
        call_args = mock_db.update_turn_response.call_args
        assert call_args[1]["response"] == "Answer" or call_args[0][4] == "Answer"

    @patch("backend.streaming.chat_stream._publish_chunk")
    @patch("backend.streaming.chat_stream._read_s3_text")
    @patch("backend.streaming.chat_stream.boto3")
    @patch("backend.streaming.chat_stream.db")
    def test_bedrock_error_publishes_error_chunk(self, mock_db, mock_boto3, mock_s3_read, mock_publish):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = {
            "conv_id": "paper1",
            "full_text_s3_key": "key",
        }
        mock_db.get_conversation_turns.return_value = []
        mock_db.get_full_profile.return_value = {"summaries": []}
        mock_s3_read.return_value = "Paper text"

        mock_bedrock = MagicMock()
        mock_boto3.client.return_value = mock_bedrock
        mock_bedrock.invoke_model_with_response_stream.side_effect = Exception("Bedrock timeout")

        result = handler(_make_event(), None)

        assert result["status"] == "error:llm_failed"
        mock_publish.assert_called_with("paper1", 1, "[Error: LLM streaming failed]", True)

    @patch("backend.streaming.chat_stream._publish_chunk")
    @patch("backend.streaming.chat_stream._read_s3_text")
    @patch("backend.streaming.chat_stream.boto3")
    @patch("backend.streaming.chat_stream.db")
    def test_excludes_current_turn_from_history(self, mock_db, mock_boto3, mock_s3_read, mock_publish):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = {
            "conv_id": "paper1",
            "full_text_s3_key": "key",
        }
        # Simulate 2 prior turns + the current (seq=3) turn
        mock_db.get_conversation_turns.return_value = [
            {"seq": 1, "request": "q1", "response": "a1"},
            {"seq": 2, "request": "q2", "response": "a2"},
            {"seq": 3, "request": "current question", "response": None},
        ]
        mock_db.get_full_profile.return_value = {"summaries": []}
        mock_s3_read.return_value = "Paper text"

        mock_bedrock = MagicMock()
        mock_boto3.client.return_value = mock_bedrock
        mock_bedrock.invoke_model_with_response_stream.return_value = {"body": [
            {"chunk": {"bytes": json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}}).encode()}},
        ]}

        handler(_make_event(turn_seq=3, message="current question"), None)

        # Verify _build_messages was called without the seq=3 turn
        # The LLM should only see turns 1 and 2 as history
        call_args = mock_bedrock.invoke_model_with_response_stream.call_args
        body = json.loads(call_args[1]["body"])
        messages = body["messages"]
        # 2 history turns (q1/a1, q2/a2) + new message = 5 messages total
        assert len(messages) == 5
        assert messages[-1]["content"] == "current question"

"""Tests for the chat dispatch handler (AppSync resolver)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backend.streaming.chat_dispatch import handler


def _make_event(sub="test-user", paper_id="paper1", message="hello"):
    return {
        "identity": {"sub": sub},
        "arguments": {"paperId": paper_id, "message": message},
    }


class TestDispatchHandler:
    def test_no_auth_returns_error(self):
        event = {"identity": {}, "arguments": {"paperId": "p", "message": "hi"}}
        result = handler(event, None)
        assert result["status"] == "error:unauthorized"

    def test_missing_paper_id_returns_error(self):
        event = _make_event(paper_id="")
        result = handler(event, None)
        assert result["status"] == "error:missing_fields"

    def test_missing_message_returns_error(self):
        event = _make_event(message="")
        result = handler(event, None)
        assert result["status"] == "error:missing_fields"

    @patch("backend.streaming.chat_dispatch.boto3")
    @patch("backend.streaming.chat_dispatch.db")
    def test_creates_conversation_if_not_exists(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = MagicMock()
        mock_db.get_conversation_by_paper.return_value = None
        mock_db.create_conversation.return_value = {"conv_id": "paper1"}
        mock_db.get_conversation_turns.return_value = []

        result = handler(_make_event(), None)

        assert result["status"] == "ok"
        mock_db.create_conversation.assert_called_once()

    @patch("backend.streaming.chat_dispatch.boto3")
    @patch("backend.streaming.chat_dispatch.db")
    def test_returns_correct_turn_seq(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = MagicMock()
        mock_db.get_conversation_by_paper.return_value = {"conv_id": "paper1"}
        # 3 existing turns → next seq = 4
        mock_db.get_conversation_turns.return_value = [
            {"seq": 1}, {"seq": 2}, {"seq": 3}
        ]

        result = handler(_make_event(), None)

        assert result["turnSeq"] == 4
        assert result["conversationId"] == "paper1"

    @patch("backend.streaming.chat_dispatch.boto3")
    @patch("backend.streaming.chat_dispatch.db")
    def test_invokes_stream_lambda_async(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_lambda = MagicMock()
        mock_boto3.client.return_value = mock_lambda
        mock_db.get_conversation_by_paper.return_value = {"conv_id": "paper1"}
        mock_db.get_conversation_turns.return_value = []

        handler(_make_event(), None)

        mock_lambda.invoke.assert_called_once()
        call_kwargs = mock_lambda.invoke.call_args[1]
        assert call_kwargs["InvocationType"] == "Event"
        payload = json.loads(call_kwargs["Payload"])
        assert payload["user_id"] == "test-user"
        assert payload["paper_id"] == "paper1"
        assert payload["message"] == "hello"
        assert payload["turn_seq"] == 1

    @patch("backend.streaming.chat_dispatch.boto3")
    @patch("backend.streaming.chat_dispatch.db")
    def test_writes_turn_to_ddb(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = MagicMock()
        mock_db.get_conversation_by_paper.return_value = {"conv_id": "paper1"}
        mock_db.get_conversation_turns.return_value = []

        handler(_make_event(), None)

        mock_db.put_turn.assert_called_once()
        mock_db.update_conversation_last_active.assert_called_once()

    @patch("backend.streaming.chat_dispatch.boto3")
    @patch("backend.streaming.chat_dispatch.db")
    def test_extracts_user_from_claims_fallback(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = MagicMock()
        mock_db.get_conversation_by_paper.return_value = {"conv_id": "paper1"}
        mock_db.get_conversation_turns.return_value = []

        # sub in claims instead of top-level identity
        event = {
            "identity": {"claims": {"sub": "user-from-claims"}},
            "arguments": {"paperId": "paper1", "message": "hi"},
        }
        result = handler(event, None)

        assert result["status"] == "ok"

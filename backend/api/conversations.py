"""API handler: Conversation listing and history."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for conversation API.

    GET /conversations — list all conversations for user
    GET /conversations/{conv_id} — conversation history (META + turns)
    GET /conversations/{conv_id}/archive/{batch_id} — archived turns
    """
    raise NotImplementedError("Conversations API — M1 build step")

"""API handler: Feed reads (paginated card listing + single card)."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for feed API.

    GET /feed — paginated feed cards, newest first
    GET /feed/{card_id} — single card detail
    """
    raise NotImplementedError("Feed API — M0 build step")

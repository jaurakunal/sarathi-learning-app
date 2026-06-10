"""API handler: Log engagement events."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for engagement logging.

    POST /engagement — log a user action (view, expand, read, dismiss, etc.)
    """
    raise NotImplementedError("Engagement API — M1 build step")

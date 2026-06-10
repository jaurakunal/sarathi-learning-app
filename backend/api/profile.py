"""API handler: Profile reads."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for profile API.

    GET /profile — full profile (all areas, hypothesis, summaries)
    GET /profile/areas — list areas only
    GET /profile/hypothesis — hypothesis with evidence
    """
    raise NotImplementedError("Profile API — M1 build step")

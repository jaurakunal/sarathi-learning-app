"""Pipeline step: Nightly learning loop."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for the Learn step.

    1. Read engagement events since last run
    2. LLM analyzes engagement patterns + questions asked
    3. Update profile items: frontiers, reading_speed, area status
    4. Regenerate ALL tiered summaries (yesterday/3d/7d/month/quarter)
    5. Append profile_history events for any changes
    """
    raise NotImplementedError("Learn step — M1 build step")

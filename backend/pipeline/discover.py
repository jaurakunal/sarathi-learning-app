"""Pipeline step: Discover candidate papers from all sources."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for the Discover step.

    Reads profile areas from DDB, queries all sources, writes candidate
    paper records to DDB (deduplicating against already-seen papers).
    """
    raise NotImplementedError("Discover step — M0 build step")

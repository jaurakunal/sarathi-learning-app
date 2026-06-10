"""Pipeline step: Select top papers within time budget."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for the Select step.

    Ranks triaged papers, applies time-budget cap (~3 deep or ~5 micro),
    applies quality floor (is the best one better than resurfacing from library?).
    Marks selected papers as 'surfaced', rest as 'skipped'.
    If dry week: generates resurface/connect/brainstorm/challenge cards instead.
    """
    raise NotImplementedError("Select step — M0 build step")

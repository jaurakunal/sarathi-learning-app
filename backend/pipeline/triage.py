"""Pipeline step: Triage candidate papers using LLM."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for the Triage step.

    Reads candidate papers + profile from DDB. LLM scores each paper's
    abstract against the profile (relevance, level, hypothesis fit).
    Updates triage_score and triage_reasoning on each paper record.
    """
    raise NotImplementedError("Triage step — M0 build step")

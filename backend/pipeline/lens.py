"""Pipeline step: Tag hypothesis relevance on feed cards."""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    """Lambda handler for the Lens step.

    Reads each new feed_card, evaluates against the hypothesis
    (supports / refutes / refines), writes hypothesis_relevance field.
    """
    raise NotImplementedError("Lens step — M0 build step")

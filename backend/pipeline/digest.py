"""Pipeline step: Generate hook + multi-level digest for selected papers.

This runs as a Fargate task (not Lambda) because it's LLM-heavy and may
exceed the 15-minute Lambda timeout for multiple papers.
"""

from __future__ import annotations


def run(event: dict) -> dict:
    """Fargate entrypoint for the Digest step.

    For each surfaced paper:
    1. Fetch full text from source
    2. Store full text in S3
    3. Generate: hook, why_you_now, digest (gist + key_ideas + deep),
       glossary, math_notes, hypothesis_relevance, honesty_note,
       suggested_questions
    4. Write feed_card to DDB
    """
    raise NotImplementedError("Digest step — M0 build step")


if __name__ == "__main__":
    import json
    import sys

    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    run(event)

"""Pipeline step: Tag hypothesis relevance on feed cards.

This is a lightweight annotation pass that runs after the Digest step.
The Digest step already generates an initial hypothesis_relevance field,
but this Lens step validates and refines it for consistency using a
focused LLM call with just the hypothesis + card summary.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import anthropic
import boto3

from backend.shared import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SYSTEM_PROMPT = (
    "You evaluate whether a research paper supports, refutes, or refines a given hypothesis. "
    "Be specific and honest. If the paper is irrelevant to the hypothesis, say so plainly."
)


def _build_user_message(hypothesis_statement: str, card: dict) -> str:
    """Construct the user message with hypothesis and card content."""
    hook = card.get("hook", "")

    # Extract digest fields — digest may be a dict or nested object
    digest = card.get("digest", {})
    if isinstance(digest, dict):
        gist = digest.get("gist", "")
        key_ideas = digest.get("key_ideas", [])
    else:
        gist = ""
        key_ideas = []

    key_ideas_text = "\n".join(f"- {idea}" for idea in key_ideas) if key_ideas else "(none)"

    return (
        f"## Hypothesis\n\n"
        f"{hypothesis_statement}\n\n"
        f"## Paper Summary\n\n"
        f"**Hook:** {hook}\n\n"
        f"**Gist:** {gist}\n\n"
        f"**Key Ideas:**\n{key_ideas_text}\n\n"
        f"## Question\n\n"
        f"Does this paper support, refute, or refine the hypothesis above? "
        f"How specifically? Provide a 1-2 sentence assessment."
    )


def _annotate_card(
    client: anthropic.Anthropic,
    model: str,
    hypothesis_statement: str,
    card: dict,
) -> str | None:
    """Call the LLM to evaluate a single card against the hypothesis.

    Returns the annotation string, or None on failure.
    """
    try:
        response = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": _build_user_message(hypothesis_statement, card),
                },
            ],
            system=SYSTEM_PROMPT,
        )
        text = response.content[0].text.strip()
        return text

    except anthropic.APIError as e:
        logger.error(
            "Anthropic API error annotating card %s: %s",
            card.get("card_id", "unknown"),
            str(e),
        )
        return None
    except (IndexError, TypeError, AttributeError) as e:
        logger.warning(
            "Failed to parse LLM response for card %s: %s",
            card.get("card_id", "unknown"),
            str(e),
        )
        return None


def _needs_annotation(card: dict) -> bool:
    """Check whether a card still needs hypothesis_relevance annotation."""
    relevance = card.get("hypothesis_relevance")
    return not relevance or not relevance.strip()


def _today_prefix() -> str:
    """Return today's date as a card_id timestamp prefix for filtering (YYYYMMDD)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def handler(event: dict, context) -> dict:
    """Lambda handler for the Lens step.

    Reads each new feed_card, evaluates against the hypothesis
    (supports / refutes / refines), writes hypothesis_relevance field.

    Event:
        user_id: str - the user whose cards to annotate
        table_name: str - DynamoDB table name
        model: str (optional) - Anthropic model, default claude-sonnet-4-20250514
    """
    user_id = event["user_id"]
    table_name = event["table_name"]
    model = event.get("model", "claude-sonnet-4-20250514")

    # Set up DynamoDB table resource
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # 1. Load user hypothesis
    profile = db.get_full_profile(table, user_id)
    hypothesis_item = profile.get("hypothesis")
    if not hypothesis_item:
        logger.warning("No hypothesis found for user %s — skipping lens.", user_id)
        return {"cards_annotated": 0}

    hypothesis_statement = hypothesis_item.get("statement", "")
    if not hypothesis_statement:
        logger.warning("Hypothesis statement is empty for user %s — skipping.", user_id)
        return {"cards_annotated": 0}

    # 2. List recent feed cards (today's cards, generous limit)
    today = _today_prefix()
    cards, _ = db.list_feed_cards(table, user_id, limit=50)

    # Filter to today's cards based on card_id prefix (card_ids are timestamped)
    todays_cards = [c for c in cards if c.get("card_id", "").startswith(today)]

    # If no cards from today specifically, fall back to all recent cards
    # that still need annotation (handles timezone edge cases)
    if not todays_cards:
        todays_cards = cards

    # Filter to cards that need annotation
    cards_to_annotate = [c for c in todays_cards if _needs_annotation(c)]

    if not cards_to_annotate:
        logger.info("No cards need annotation for user %s.", user_id)
        return {"cards_annotated": 0}

    # 3. Set up Anthropic client
    client = anthropic.Anthropic()

    # 4. Annotate each card
    cards_annotated = 0

    for card in cards_to_annotate:
        card_id = card.get("card_id", "")
        logger.info("Annotating card %s for hypothesis relevance.", card_id)

        annotation = _annotate_card(client, model, hypothesis_statement, card)

        if annotation is None:
            logger.warning("Skipping card %s — annotation failed.", card_id)
            continue

        # Update the card with hypothesis_relevance and write back to DDB
        card["hypothesis_relevance"] = annotation
        db.put_feed_card(table, user_id, card)
        cards_annotated += 1

    logger.info(
        "Lens complete for user %s: %d cards annotated.", user_id, cards_annotated
    )

    return {"cards_annotated": cards_annotated}

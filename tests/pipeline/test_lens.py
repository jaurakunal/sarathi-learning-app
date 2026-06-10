"""Tests for backend.pipeline.lens — the Lens pipeline step."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Happy path: cards without hypothesis_relevance get annotated
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.anthropic")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_happy_path_cards_annotated(mock_db, mock_boto3, mock_anthropic, user_id, table_name, sample_profile, sample_feed_cards):
    """Cards missing hypothesis_relevance get annotated by LLM."""
    from backend.pipeline.lens import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = sample_profile

    # First card has empty hypothesis_relevance → needs annotation
    # The second card already has it → should be skipped
    cards = [sample_feed_cards[0].copy(), sample_feed_cards[1].copy()]
    assert cards[0]["hypothesis_relevance"] == ""  # Needs annotation
    assert cards[1]["hypothesis_relevance"] != ""  # Already has one

    mock_db.list_feed_cards.return_value = (cards, None)

    # Mock Anthropic client
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    llm_response = MagicMock()
    llm_response.content = [MagicMock()]
    llm_response.content[0].text = "Supports: memory architecture is key to faithful clones."
    mock_client.messages.create.return_value = llm_response

    # Patch _today_prefix to match card_id prefix
    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["cards_annotated"] == 1

    # Verify put_feed_card was called with the annotated card
    mock_db.put_feed_card.assert_called_once()
    call_args = mock_db.put_feed_card.call_args[0]
    assert call_args[0] is mock_table
    assert call_args[1] == user_id
    annotated_card = call_args[2]
    assert annotated_card["hypothesis_relevance"] == "Supports: memory architecture is key to faithful clones."
    assert annotated_card["card_id"] == sample_feed_cards[0]["card_id"]


# ---------------------------------------------------------------------------
# Card already has hypothesis_relevance → skipped
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.anthropic")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_already_annotated_card_skipped(mock_db, mock_boto3, mock_anthropic, user_id, table_name, sample_profile, sample_feed_cards):
    """Cards that already have hypothesis_relevance are not re-annotated."""
    from backend.pipeline.lens import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = sample_profile

    # Only return the card that already has hypothesis_relevance
    cards = [sample_feed_cards[1].copy()]  # This one already has annotation
    mock_db.list_feed_cards.return_value = (cards, None)

    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["cards_annotated"] == 0
    mock_db.put_feed_card.assert_not_called()


# ---------------------------------------------------------------------------
# LLM failure → card skipped, others continue
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.anthropic")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_llm_failure_skips_card(mock_db, mock_boto3, mock_anthropic, user_id, table_name, sample_profile):
    """When LLM call fails, that card is skipped but others continue."""
    from backend.pipeline.lens import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = sample_profile

    # Two cards needing annotation
    cards = [
        {
            "card_id": "20260607_120000_aaaa1111",
            "paper_id": "p1",
            "hook": "Hook 1",
            "digest": {"gist": "Gist 1", "key_ideas": ["Idea"]},
            "hypothesis_relevance": "",
        },
        {
            "card_id": "20260607_120100_bbbb2222",
            "paper_id": "p2",
            "hook": "Hook 2",
            "digest": {"gist": "Gist 2", "key_ideas": ["Idea 2"]},
            "hypothesis_relevance": "",
        },
    ]
    mock_db.list_feed_cards.return_value = (cards, None)

    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    # Set up APIError on the mocked anthropic module
    mock_anthropic.APIError = type("APIError", (Exception,), {})

    # First call raises API error, second succeeds
    good_response = MagicMock()
    good_response.content = [MagicMock()]
    good_response.content[0].text = "Refines: adds nuance to the harness hypothesis."

    mock_client.messages.create.side_effect = [
        mock_anthropic.APIError("server error"),
        good_response,
    ]

    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        result = handler({"user_id": user_id, "table_name": table_name}, None)

    # First card failed, second succeeded
    assert result["cards_annotated"] == 1
    mock_db.put_feed_card.assert_called_once()


# ---------------------------------------------------------------------------
# No hypothesis in profile → returns {cards_annotated: 0}
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.anthropic")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_no_hypothesis_returns_zero(mock_db, mock_boto3, mock_anthropic, user_id, table_name):
    """When user has no hypothesis, handler returns zero without calling LLM."""
    from backend.pipeline.lens import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    # Profile without hypothesis
    mock_db.get_full_profile.return_value = {
        "meta": {"learning_style": {}},
        "areas": [{"label": "Test"}],
        "hypothesis": None,
        "summaries": [],
    }

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["cards_annotated"] == 0


# ---------------------------------------------------------------------------
# Empty hypothesis statement → returns {cards_annotated: 0}
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.anthropic")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_empty_hypothesis_statement_returns_zero(mock_db, mock_boto3, mock_anthropic, user_id, table_name):
    """When hypothesis exists but statement is empty, returns zero."""
    from backend.pipeline.lens import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = {
        "meta": {"learning_style": {}},
        "areas": [],
        "hypothesis": {"statement": "", "status": "untested"},
        "summaries": [],
    }

    result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["cards_annotated"] == 0


# ---------------------------------------------------------------------------
# No cards needing annotation → returns zero
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.anthropic")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_no_cards_needing_annotation(mock_db, mock_boto3, mock_anthropic, user_id, table_name, sample_profile):
    """When all cards already have hypothesis_relevance, returns zero."""
    from backend.pipeline.lens import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = sample_profile

    # All cards already annotated
    cards = [
        {
            "card_id": "20260607_120000_xxxx",
            "hypothesis_relevance": "Supports: already annotated.",
        },
        {
            "card_id": "20260607_120100_yyyy",
            "hypothesis_relevance": "Refutes: already annotated.",
        },
    ]
    mock_db.list_feed_cards.return_value = (cards, None)

    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        result = handler({"user_id": user_id, "table_name": table_name}, None)

    assert result["cards_annotated"] == 0


# ---------------------------------------------------------------------------
# Verify correct arguments passed to db functions
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.anthropic")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_db_calls_correct_arguments(mock_db, mock_boto3, mock_anthropic, user_id, table_name, sample_profile):
    """Verify db.get_full_profile, list_feed_cards, put_feed_card receive correct args."""
    from backend.pipeline.lens import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = sample_profile

    cards = [
        {
            "card_id": "20260607_120000_test1234",
            "paper_id": "paper-001",
            "hook": "Test hook",
            "digest": {"gist": "Test gist", "key_ideas": ["Idea"]},
            "hypothesis_relevance": "",
        },
    ]
    mock_db.list_feed_cards.return_value = (cards, None)

    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    llm_response = MagicMock()
    llm_response.content = [MagicMock()]
    llm_response.content[0].text = "Annotation result"
    mock_client.messages.create.return_value = llm_response

    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        handler({"user_id": user_id, "table_name": table_name}, None)

    # Verify get_full_profile
    mock_db.get_full_profile.assert_called_once_with(mock_table, user_id)

    # Verify list_feed_cards
    mock_db.list_feed_cards.assert_called_once_with(mock_table, user_id, limit=50)

    # Verify put_feed_card
    mock_db.put_feed_card.assert_called_once()
    args = mock_db.put_feed_card.call_args[0]
    assert args[0] is mock_table
    assert args[1] == user_id
    assert args[2]["hypothesis_relevance"] == "Annotation result"


# ---------------------------------------------------------------------------
# _needs_annotation correctly identifies cards needing work
# ---------------------------------------------------------------------------

def test_needs_annotation_empty_string():
    """Card with empty hypothesis_relevance needs annotation."""
    from backend.pipeline.lens import _needs_annotation

    assert _needs_annotation({"hypothesis_relevance": ""}) is True


def test_needs_annotation_whitespace_only():
    """Card with whitespace-only hypothesis_relevance needs annotation."""
    from backend.pipeline.lens import _needs_annotation

    assert _needs_annotation({"hypothesis_relevance": "   "}) is True


def test_needs_annotation_none():
    """Card with None hypothesis_relevance needs annotation."""
    from backend.pipeline.lens import _needs_annotation

    assert _needs_annotation({"hypothesis_relevance": None}) is True


def test_needs_annotation_missing_key():
    """Card without hypothesis_relevance key needs annotation."""
    from backend.pipeline.lens import _needs_annotation

    assert _needs_annotation({"card_id": "test"}) is True


def test_needs_annotation_has_content():
    """Card with actual hypothesis_relevance content does not need annotation."""
    from backend.pipeline.lens import _needs_annotation

    assert _needs_annotation({"hypothesis_relevance": "Supports the hypothesis."}) is False


# ---------------------------------------------------------------------------
# Fallback: when no cards match today prefix, all cards are considered
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.anthropic")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_fallback_when_no_today_cards(mock_db, mock_boto3, mock_anthropic, user_id, table_name, sample_profile):
    """When no cards match today's prefix, all recent cards are considered."""
    from backend.pipeline.lens import handler

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = sample_profile

    # Cards from yesterday (won't match today's prefix)
    cards = [
        {
            "card_id": "20260606_120000_abcd",  # Yesterday
            "paper_id": "p1",
            "hook": "Hook",
            "digest": {"gist": "Gist", "key_ideas": []},
            "hypothesis_relevance": "",
        },
    ]
    mock_db.list_feed_cards.return_value = (cards, None)

    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    llm_response = MagicMock()
    llm_response.content = [MagicMock()]
    llm_response.content[0].text = "Supports the hypothesis."
    mock_client.messages.create.return_value = llm_response

    # Today's prefix won't match "20260606" cards
    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        result = handler({"user_id": user_id, "table_name": table_name}, None)

    # Fallback: all cards considered since no today cards found
    assert result["cards_annotated"] == 1

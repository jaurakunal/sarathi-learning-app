"""Tests for backend.pipeline.lens — the Lens pipeline step."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Happy path: cards without hypothesis_relevance get annotated
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_happy_path_cards_annotated(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_profile, sample_feed_cards):
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

    # call_llm returns a plain string (not JSON for lens)
    mock_call_llm.return_value = "Supports: memory architecture is key to faithful clones."

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

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_already_annotated_card_skipped(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_profile, sample_feed_cards):
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

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_llm_failure_skips_card(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_profile):
    """When LLM call fails (returns None), that card is skipped but others continue."""
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

    # First call returns None (API failure), second succeeds
    mock_call_llm.side_effect = [
        None,
        "Refines: adds nuance to the harness hypothesis.",
    ]

    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        result = handler({"user_id": user_id, "table_name": table_name}, None)

    # First card failed, second succeeded
    assert result["cards_annotated"] == 1
    mock_db.put_feed_card.assert_called_once()


# ---------------------------------------------------------------------------
# No hypothesis in profile → returns {cards_annotated: 0}
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_no_hypothesis_returns_zero(mock_db, mock_boto3, mock_call_llm, user_id, table_name):
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

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_empty_hypothesis_statement_returns_zero(mock_db, mock_boto3, mock_call_llm, user_id, table_name):
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

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_no_cards_needing_annotation(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_profile):
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

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_db_calls_correct_arguments(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_profile):
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

    mock_call_llm.return_value = "Annotation result"

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

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_fallback_when_no_today_cards(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_profile):
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

    mock_call_llm.return_value = "Supports the hypothesis."

    # Today's prefix won't match "20260606" cards
    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        result = handler({"user_id": user_id, "table_name": table_name}, None)

    # Fallback: all cards considered since no today cards found
    assert result["cards_annotated"] == 1


# ---------------------------------------------------------------------------
# Lens uses call_llm_with_fallback with Kimi primary + Sonnet fallback
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_uses_fallback_wrapper_with_kimi_primary(
    mock_db, mock_boto3, mock_fallback,
    user_id, table_name, sample_profile,
):
    """_annotate_card goes through call_llm_with_fallback with Kimi + Sonnet fallback."""
    from backend.pipeline.lens import handler, FALLBACK_MODEL

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = sample_profile

    cards = [{
        "card_id": "20260607_120000_test1234",
        "paper_id": "paper-001",
        "hook": "Test hook",
        "digest": {"gist": "Test gist", "key_ideas": ["Idea"]},
        "hypothesis_relevance": "",
    }]
    mock_db.list_feed_cards.return_value = (cards, None)

    mock_fallback.return_value = "Supports."

    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        handler({
            "user_id": user_id,
            "table_name": table_name,
            "model": "moonshotai.kimi-k2.5",
        }, None)

    mock_fallback.assert_called_once()
    kwargs = mock_fallback.call_args.kwargs
    assert kwargs["primary_model"] == "moonshotai.kimi-k2.5"
    assert kwargs["fallback_model"] == FALLBACK_MODEL
    assert FALLBACK_MODEL == "us.anthropic.claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Lens handler defaults to LENS_MODEL env (Kimi K2.5) when 'model' missing
# ---------------------------------------------------------------------------

@patch("backend.pipeline.lens.call_llm_with_fallback")
@patch("backend.pipeline.lens.boto3")
@patch("backend.pipeline.lens.db")
def test_default_model_when_event_omits_it(
    mock_db, mock_boto3, mock_fallback,
    user_id, table_name, sample_profile,
):
    """When event has no 'model' key, falls back to module DEFAULT_MODEL (env-driven)."""
    from backend.pipeline.lens import handler, DEFAULT_MODEL

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table

    mock_db.get_full_profile.return_value = sample_profile

    cards = [{
        "card_id": "20260607_120000_x",
        "paper_id": "paper-001",
        "hook": "Test",
        "digest": {"gist": "G", "key_ideas": []},
        "hypothesis_relevance": "",
    }]
    mock_db.list_feed_cards.return_value = (cards, None)

    mock_fallback.return_value = "Supports."

    with patch("backend.pipeline.lens._today_prefix", return_value="20260607"):
        handler({"user_id": user_id, "table_name": table_name}, None)

    kwargs = mock_fallback.call_args.kwargs
    assert kwargs["primary_model"] == DEFAULT_MODEL

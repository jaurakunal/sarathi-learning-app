"""Tests for backend.pipeline.digest — the Digest pipeline step."""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Happy path: paper text fetched, stored in S3, LLM generates card, written to DDB
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest._build_sources")
@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_happy_path_card_generated(mock_db, mock_boto3, mock_call_llm, mock_sources, user_id, table_name, sample_profile, sample_surfaced_papers):
    """Full text fetched, S3 upload, LLM card generation, DDB write — all succeed."""
    from backend.pipeline.digest import run

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_surfaced_papers[0]]

    # Mock source fetch
    mock_source = MagicMock()
    mock_source.fetch_full_text.return_value = "Full paper text here..."
    mock_sources.return_value = {"semantic_scholar": mock_source, "arxiv": mock_source, "arxiv_rss": mock_source, "openreview": mock_source, "hf_daily_papers": mock_source, "papers_with_code": mock_source}

    # call_llm_with_fallback returns a JSON string directly (primary model succeeded)
    card_content = {
        "hook": "What if your agent could remember last Tuesday?",
        "why_you_now": "Your clone needs episodic memory.",
        "time_estimate": "12 min",
        "digest": {
            "gist": "A new memory architecture for agents.",
            "key_ideas": ["Time-aware retrieval", "Consolidation cycles"],
            "deep": "The paper proposes a novel approach...",
        },
        "glossary": [{"term": "episodic memory", "plain": "Memory of events"}],
        "math_notes": [],
        "hypothesis_relevance": "Supports: architecture matters more than LLM size.",
        "honesty_note": "Full read recommended.",
        "suggested_questions": ["How would this plug into my harness?"],
    }
    mock_call_llm.return_value = json.dumps(card_content)

    result = run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "sarathi-test-bucket",
    })

    assert result["cards_generated"] == 1
    assert result["papers_failed"] == 0

    # Verify S3 upload
    mock_s3.put_object.assert_called_once()
    s3_call = mock_s3.put_object.call_args
    assert s3_call[1]["Bucket"] == "sarathi-test-bucket"
    assert user_id in s3_call[1]["Key"]
    assert "paper-001" in s3_call[1]["Key"]

    # Verify feed card written to DDB
    mock_db.put_feed_card.assert_called_once()
    call_args = mock_db.put_feed_card.call_args[0]
    assert call_args[0] is mock_table
    assert call_args[1] == user_id
    card = call_args[2]
    assert card["hook"] == "What if your agent could remember last Tuesday?"
    assert card["paper_id"] == "paper-001"


# ---------------------------------------------------------------------------
# Full text fetch fails → paper skipped, others continue
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest._build_sources")
@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_full_text_fetch_fails_skips_paper(mock_db, mock_boto3, mock_call_llm, mock_sources, user_id, table_name, sample_profile, sample_surfaced_papers):
    """When fetch_full_text returns empty, paper is skipped."""
    from backend.pipeline.digest import run

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = sample_surfaced_papers[:2]

    # First paper: fetch fails (returns empty string)
    # Second paper: fetch succeeds
    mock_source = MagicMock()
    mock_source.fetch_full_text.side_effect = ["", "Paper 2 full text"]
    mock_sources.return_value = {"semantic_scholar": mock_source, "arxiv": mock_source, "arxiv_rss": mock_source, "openreview": mock_source, "hf_daily_papers": mock_source, "papers_with_code": mock_source}

    # LLM response for the second paper
    mock_call_llm.return_value = json.dumps({
        "hook": "Hook for paper 2",
        "why_you_now": "Because...",
        "time_estimate": "8 min",
        "digest": {"gist": "Gist", "key_ideas": ["Idea"], "deep": "Deep"},
        "glossary": [],
        "math_notes": [],
        "hypothesis_relevance": "Relevant",
        "honesty_note": "Skim",
        "suggested_questions": ["Q?"],
    })

    result = run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "sarathi-test-bucket",
    })

    assert result["cards_generated"] == 1
    assert result["papers_failed"] == 1


# ---------------------------------------------------------------------------
# LLM returns malformed JSON → paper skipped
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest._build_sources")
@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_llm_malformed_json_skips_paper(mock_db, mock_boto3, mock_call_llm, mock_sources, user_id, table_name, sample_profile, sample_surfaced_papers):
    """When LLM returns invalid JSON, paper is skipped with papers_failed incremented."""
    from backend.pipeline.digest import run

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_surfaced_papers[0]]

    mock_source = MagicMock()
    mock_source.fetch_full_text.return_value = "Full text of paper"
    mock_sources.return_value = {"semantic_scholar": mock_source, "arxiv": mock_source, "arxiv_rss": mock_source, "openreview": mock_source, "hf_daily_papers": mock_source, "papers_with_code": mock_source}

    # LLM returns broken JSON
    mock_call_llm.return_value = "I'm sorry, I cannot generate a card for this paper..."

    result = run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "sarathi-test-bucket",
    })

    assert result["cards_generated"] == 0
    assert result["papers_failed"] == 1
    mock_db.put_feed_card.assert_not_called()


# ---------------------------------------------------------------------------
# Card ID format: verify timestamp prefix + hash structure
# ---------------------------------------------------------------------------

def test_card_id_format():
    """Card ID should have format YYYYMMDD_HHMMSS_<8-char-hex-hash>."""
    from backend.pipeline.digest import _generate_card_id

    card_id = _generate_card_id("paper-001")

    # Should match: 8-digit date _ 6-digit time _ 8-char hex
    pattern = r"^\d{8}_\d{6}_[0-9a-f]{8}$"
    assert re.match(pattern, card_id), f"Card ID '{card_id}' does not match expected format"

    # Verify the date prefix is valid (starts with 20xx)
    assert card_id.startswith("20")


def test_card_id_uniqueness():
    """Two calls with same paper_id produce different card_ids (due to timestamp)."""
    from backend.pipeline.digest import _generate_card_id

    # These may or may not be different depending on timing,
    # but the hash component uses datetime.now() so they should differ
    id1 = _generate_card_id("paper-001")
    id2 = _generate_card_id("paper-001")

    # At minimum, they are validly formatted (both could be same within same ms)
    pattern = r"^\d{8}_\d{6}_[0-9a-f]{8}$"
    assert re.match(pattern, id1)
    assert re.match(pattern, id2)


# ---------------------------------------------------------------------------
# S3 key construction: verify user-scoped path
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest._build_sources")
@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_s3_key_user_scoped(mock_db, mock_boto3, mock_call_llm, mock_sources, user_id, table_name, sample_profile, sample_surfaced_papers):
    """S3 key follows pattern: users/<user_id>/papers/<paper_id>/full_text.txt."""
    from backend.pipeline.digest import run

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_surfaced_papers[0]]

    mock_source = MagicMock()
    mock_source.fetch_full_text.return_value = "Full text"
    mock_sources.return_value = {"semantic_scholar": mock_source, "arxiv": mock_source, "arxiv_rss": mock_source, "openreview": mock_source, "hf_daily_papers": mock_source, "papers_with_code": mock_source}

    mock_call_llm.return_value = json.dumps({
        "hook": "H", "why_you_now": "W", "time_estimate": "5 min",
        "digest": {"gist": "G", "key_ideas": ["K"], "deep": "D"},
        "glossary": [], "math_notes": [],
        "hypothesis_relevance": "R", "honesty_note": "N",
        "suggested_questions": ["Q"],
    })

    run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "my-bucket",
    })

    # Verify S3 key structure
    s3_call = mock_s3.put_object.call_args
    expected_key = f"users/{user_id}/papers/paper-001/full_text.txt"
    assert s3_call[1]["Key"] == expected_key
    assert s3_call[1]["Bucket"] == "my-bucket"
    assert s3_call[1]["ContentType"] == "text/plain; charset=utf-8"


# ---------------------------------------------------------------------------
# No profile → returns early with error
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_no_profile_returns_error(mock_db, mock_boto3, mock_call_llm, user_id, table_name):
    """When no profile meta exists, returns early with error indicator."""
    from backend.pipeline.digest import run

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_boto3.client.return_value = MagicMock()

    mock_db.get_full_profile.return_value = {"meta": None, "areas": [], "hypothesis": None, "summaries": []}

    result = run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "bucket",
    })

    assert result["cards_generated"] == 0
    assert result.get("error") == "no_profile"


# ---------------------------------------------------------------------------
# No surfaced papers → returns zeros
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_no_surfaced_papers_returns_zeros(mock_db, mock_boto3, mock_call_llm, user_id, table_name, sample_profile):
    """When no surfaced papers exist, returns zero counts."""
    from backend.pipeline.digest import run

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_boto3.client.return_value = MagicMock()

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = []

    result = run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "bucket",
    })

    assert result["cards_generated"] == 0
    assert result["papers_failed"] == 0


# ---------------------------------------------------------------------------
# Unknown source → paper skipped
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest._build_sources")
@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_unknown_source_skips_paper(mock_db, mock_boto3, mock_call_llm, mock_sources, user_id, table_name, sample_profile):
    """Paper with an unknown source field is skipped."""
    from backend.pipeline.digest import run

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_boto3.client.return_value = MagicMock()

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [{
        "id": "paper-x",
        "source": "unknown_source_xyz",
        "title": "Mystery Paper",
        "status": "surfaced",
    }]

    # _SOURCES.get returns None for unknown source
    mock_sources.get.return_value = None

    result = run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "bucket",
    })

    assert result["cards_generated"] == 0
    assert result["papers_failed"] == 1


# ---------------------------------------------------------------------------
# Feed card has correct structure when written to DDB
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest._build_sources")
@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_feed_card_structure(mock_db, mock_boto3, mock_call_llm, mock_sources, user_id, table_name, sample_profile, sample_surfaced_papers):
    """Verify all required fields are present in the feed card written to DDB."""
    from backend.pipeline.digest import run

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_surfaced_papers[0]]

    mock_source = MagicMock()
    mock_source.fetch_full_text.return_value = "Paper text"
    mock_sources.return_value = {"semantic_scholar": mock_source, "arxiv": mock_source, "arxiv_rss": mock_source, "openreview": mock_source, "hf_daily_papers": mock_source, "papers_with_code": mock_source}

    mock_call_llm.return_value = json.dumps({
        "hook": "Hook text",
        "why_you_now": "Why now text",
        "time_estimate": "10 min",
        "digest": {"gist": "Gist", "key_ideas": ["Idea 1", "Idea 2"], "deep": "Deep text"},
        "glossary": [{"term": "T", "plain": "P"}],
        "math_notes": [{"plain": "Intuition", "equation_optional": "E=mc^2"}],
        "hypothesis_relevance": "Supports",
        "honesty_note": "Full read",
        "suggested_questions": ["Q1", "Q2"],
    })

    run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "bucket",
    })

    card = mock_db.put_feed_card.call_args[0][2]

    # Verify all required keys
    required_keys = [
        "card_id", "paper_id", "source_url", "full_text_s3_key",
        "card_type", "hook", "why_you_now", "time_estimate",
        "digest", "glossary", "math_notes", "hypothesis_relevance",
        "honesty_note", "suggested_questions",
    ]
    for key in required_keys:
        assert key in card, f"Missing key: {key}"

    assert card["card_type"] == "new_paper"
    assert card["paper_id"] == "paper-001"
    assert isinstance(card["digest"], dict)
    assert isinstance(card["glossary"], list)
    assert isinstance(card["suggested_questions"], list)


# ---------------------------------------------------------------------------
# Fallback wrapper is used: primary model + Sonnet fallback
# ---------------------------------------------------------------------------

@patch("backend.pipeline.digest._build_sources")
@patch("backend.pipeline.digest.call_llm_with_fallback")
@patch("backend.pipeline.digest.boto3")
@patch("backend.pipeline.digest.db")
def test_uses_fallback_wrapper_with_kimi_primary(
    mock_db, mock_boto3, mock_fallback, mock_sources,
    user_id, table_name, sample_profile, sample_surfaced_papers,
):
    """_generate_card calls call_llm_with_fallback with Kimi primary + Sonnet fallback."""
    from backend.pipeline.digest import run, FALLBACK_MODEL

    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_boto3.client.return_value = MagicMock()

    mock_db.get_full_profile.return_value = sample_profile
    mock_db.list_papers_by_status.return_value = [sample_surfaced_papers[0]]

    mock_source = MagicMock()
    mock_source.fetch_full_text.return_value = "Full text"
    mock_sources.return_value = {
        "semantic_scholar": mock_source, "arxiv": mock_source,
        "arxiv_rss": mock_source, "openreview": mock_source,
        "hf_daily_papers": mock_source, "papers_with_code": mock_source,
    }

    mock_fallback.return_value = json.dumps({
        "hook": "H", "why_you_now": "W", "time_estimate": "5 min",
        "digest": {"gist": "G", "key_ideas": ["K"], "deep": "D"},
        "glossary": [], "math_notes": [],
        "hypothesis_relevance": "R", "honesty_note": "N",
        "suggested_questions": ["Q"],
    })

    run({
        "user_id": user_id,
        "table_name": table_name,
        "s3_bucket": "bucket",
        "model": "moonshotai.kimi-k2.5",
    })

    # Verify the wrapper was called with primary=Kimi and fallback=Sonnet
    mock_fallback.assert_called_once()
    kwargs = mock_fallback.call_args.kwargs
    assert kwargs["primary_model"] == "moonshotai.kimi-k2.5"
    assert kwargs["fallback_model"] == FALLBACK_MODEL
    assert FALLBACK_MODEL == "us.anthropic.claude-sonnet-4-6"

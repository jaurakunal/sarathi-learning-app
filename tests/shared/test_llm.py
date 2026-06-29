"""Unit tests for call_llm_with_fallback in backend.shared.llm.

The wrapper tries a primary model first; on failure (None return) it falls
back to a second model. Both calls go through call_llm under the hood, which
is what we mock here so we don't reach Bedrock.
"""

from __future__ import annotations

from unittest.mock import patch

from backend.shared.llm import call_llm_with_fallback


# ---------------------------------------------------------------------------
# Primary model works → fallback is never invoked
# ---------------------------------------------------------------------------


@patch("backend.shared.llm.call_llm")
def test_call_llm_with_fallback_uses_primary_when_works(mock_call_llm):
    """When primary returns text, fallback is not called."""
    mock_call_llm.return_value = "primary response"

    result = call_llm_with_fallback(
        system="sys",
        user_message="msg",
        primary_model="moonshotai.kimi-k2.5",
        fallback_model="us.anthropic.claude-sonnet-4-6",
    )

    assert result == "primary response"
    # call_llm should have been invoked exactly once with the primary model
    assert mock_call_llm.call_count == 1
    call_kwargs = mock_call_llm.call_args.kwargs
    assert call_kwargs["model_id"] == "moonshotai.kimi-k2.5"


# ---------------------------------------------------------------------------
# Primary fails (returns None) → fallback model is invoked
# ---------------------------------------------------------------------------


@patch("backend.shared.llm.call_llm")
def test_call_llm_with_fallback_falls_back_on_failure(mock_call_llm):
    """When primary returns None, fallback is invoked and its result returned."""
    # First call (primary) returns None, second call (fallback) returns text
    mock_call_llm.side_effect = [None, "fallback response"]

    result = call_llm_with_fallback(
        system="sys",
        user_message="msg",
        primary_model="moonshotai.kimi-k2.5",
        fallback_model="us.anthropic.claude-sonnet-4-6",
    )

    assert result == "fallback response"
    assert mock_call_llm.call_count == 2

    # First invocation: primary
    first_kwargs = mock_call_llm.call_args_list[0].kwargs
    assert first_kwargs["model_id"] == "moonshotai.kimi-k2.5"

    # Second invocation: fallback
    second_kwargs = mock_call_llm.call_args_list[1].kwargs
    assert second_kwargs["model_id"] == "us.anthropic.claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Both primary and fallback fail → returns None
# ---------------------------------------------------------------------------


@patch("backend.shared.llm.call_llm")
def test_call_llm_with_fallback_returns_none_when_both_fail(mock_call_llm):
    """When both primary and fallback return None, the wrapper returns None."""
    mock_call_llm.side_effect = [None, None]

    result = call_llm_with_fallback(
        system="sys",
        user_message="msg",
        primary_model="moonshotai.kimi-k2.5",
        fallback_model="us.anthropic.claude-sonnet-4-6",
    )

    assert result is None
    assert mock_call_llm.call_count == 2


# ---------------------------------------------------------------------------
# Default fallback is Sonnet (DEFAULT_MODEL_ID)
# ---------------------------------------------------------------------------


@patch("backend.shared.llm.call_llm")
def test_default_fallback_is_sonnet(mock_call_llm):
    """When fallback_model is omitted, it defaults to DEFAULT_MODEL_ID (Sonnet)."""
    mock_call_llm.side_effect = [None, "ok"]

    result = call_llm_with_fallback(
        system="s",
        user_message="m",
        primary_model="moonshotai.kimi-k2.5",
    )

    assert result == "ok"
    second_kwargs = mock_call_llm.call_args_list[1].kwargs
    assert second_kwargs["model_id"] == "us.anthropic.claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Wrapper passes through max_tokens / temperature / region kwargs
# ---------------------------------------------------------------------------


@patch("backend.shared.llm.call_llm")
def test_passthrough_kwargs(mock_call_llm):
    """max_tokens, temperature, region are forwarded to call_llm."""
    mock_call_llm.return_value = "ok"

    call_llm_with_fallback(
        system="s",
        user_message="m",
        primary_model="moonshotai.kimi-k2.5",
        max_tokens=1234,
        temperature=0.2,
        region="eu-west-1",
    )

    call_kwargs = mock_call_llm.call_args.kwargs
    assert call_kwargs["max_tokens"] == 1234
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["region"] == "eu-west-1"

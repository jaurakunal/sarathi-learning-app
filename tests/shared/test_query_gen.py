"""Tests for intent/level-aware query generation."""

from __future__ import annotations

import json
from unittest.mock import patch

from backend.shared.models import Area
from backend.shared.query_gen import generate_queries_for_area


def _area(**kw):
    base = dict(id="a1", user_id="u1", label="Agentic evaluation",
                just_right=["trajectory eval"], frontier="new metrics")
    base.update(kw)
    return Area(**base)


@patch("backend.shared.query_gen.call_llm")
def test_intent_and_level_passed_into_prompt(mock_llm):
    mock_llm.return_value = json.dumps(["agent eval survey", "llm eval overview"])
    area = _area(intent="consume", current_level="beginner")
    out = generate_queries_for_area(area)
    assert out == ["agent eval survey", "llm eval overview"]
    msg = mock_llm.call_args.kwargs["user_message"]
    assert "Intent: consume" in msg
    assert "Level: beginner" in msg


@patch("backend.shared.query_gen.call_llm")
def test_produce_intent_flows_through(mock_llm):
    mock_llm.return_value = '["novel eval metric", "trajectory eval SOTA"]'
    area = _area(intent="produce", current_level="advanced")
    generate_queries_for_area(area)
    msg = mock_llm.call_args.kwargs["user_message"]
    assert "Intent: produce" in msg
    assert "Level: advanced" in msg


@patch("backend.shared.query_gen.call_llm")
def test_defaults_when_fields_absent(mock_llm):
    mock_llm.return_value = "[]"
    # Area defaults: intent=consume, current_level=intermediate
    area = _area()
    generate_queries_for_area(area)
    msg = mock_llm.call_args.kwargs["user_message"]
    assert "Intent: consume" in msg
    assert "Level: intermediate" in msg


@patch("backend.shared.query_gen.call_llm")
def test_falls_back_to_keywords_on_llm_failure(mock_llm):
    mock_llm.return_value = None
    area = _area(just_right=["trajectory eval", "agentbench"])
    out = generate_queries_for_area(area)
    assert out == ["trajectory eval", "agentbench"]

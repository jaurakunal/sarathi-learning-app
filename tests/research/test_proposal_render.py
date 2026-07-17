"""Tests for backend.research.proposal_render."""

from __future__ import annotations

from unittest.mock import patch

from backend.research.proposal_context import (
    EngagementCtx,
    PaperCtx,
    PinnedInsightCtx,
    ProposalContext,
)
from backend.research.proposal_render import render_bundle_md, render_proposal_md


def _rich_ctx() -> ProposalContext:
    return ProposalContext(
        workspace_name="Default",
        area_name="AI clone",
        area_description="Faithful AI clones from a personal corpus.",
        hypothesis_statement="You can build a faithful AI clone of a person.",
        background="SDE, applied practitioner",
        learning_style="reads-to-build",
        papers=[
            PaperCtx(
                paper_id="p1",
                title="Contextual Retrieval",
                authors=["Alice", "Bob", "Carol", "Dan"],
                source="arxiv",
                url="https://arxiv.org/abs/p1",
                hook="Prepending context to chunks lifts recall.",
                why_you_now="Your RAG chunks lose section context.",
                digest_gist="A cheap preprocessing trick that improves recall over long docs.",
                key_ideas=["prepend context", "50-token summary"],
                areas_matched=["AI clone"],
            ),
        ],
        pinned_insights=[
            PinnedInsightCtx(
                paper_title="Contextual Retrieval",
                paper_id="p1",
                question="What's the ~cost per chunk?",
                answer="Prompt caching brings it to ~a cent per M tokens.",
            ),
        ],
        recent_questions=["How does this compare to late chunking?"],
        engagement=EngagementCtx(
            dismissed=3, bookmarked=1, read_fully=5, source_clicked=7, pinned_turns=1,
        ),
    )


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------

def test_bundle_contains_all_section_headings():
    md = render_bundle_md(_rich_ctx())
    for h in [
        "# Research context — AI clone",
        "## Your hypothesis",
        "## Papers you've read",
        "## Pinned insights",
        "## What you've been asking",
        "## Reading signals",
        "## About you",
    ]:
        assert h in md, f"missing section: {h}"


def test_bundle_includes_paper_details():
    md = render_bundle_md(_rich_ctx())
    assert "Contextual Retrieval" in md
    assert "Prepending context to chunks lifts recall." in md
    assert "prepend context" in md
    # Authors clipped to first 3 + "et al."
    assert "Alice, Bob, Carol et al." in md
    assert "Dan" not in md


def test_bundle_deterministic_ignoring_date_line():
    md1 = render_bundle_md(_rich_ctx()).splitlines()
    md2 = render_bundle_md(_rich_ctx()).splitlines()
    # Line 2 is "Generated <date> from ..." — will match at day granularity in
    # the same test run. Strip it and compare the rest.
    non_date = [l for l in md1 if not l.startswith("*Generated ")]
    non_date2 = [l for l in md2 if not l.startswith("*Generated ")]
    assert non_date == non_date2


def test_bundle_gracefully_handles_empty_workspace():
    empty = ProposalContext(
        workspace_name="WS",
        area_name="",
        area_description="",
        hypothesis_statement="",
        background="",
        learning_style="",
    )
    md = render_bundle_md(empty)
    assert "# Research context" in md
    assert "_No hypothesis recorded yet._" in md
    assert "_No digested papers yet" in md
    assert "_No pinned insights yet" in md


def test_bundle_reading_signals_line():
    md = render_bundle_md(_rich_ctx())
    assert "5 read fully" in md
    assert "3 dismissed" in md
    assert "1 bookmarked" in md


# ---------------------------------------------------------------------------
# Full proposal (LLM-backed)
# ---------------------------------------------------------------------------

@patch("backend.research.proposal_render.call_llm_with_fallback")
def test_render_proposal_calls_llm_with_bundle_context(mock_llm):
    mock_llm.return_value = "# Draft proposal\n\n## 1. Problem\n..."
    md = render_proposal_md(_rich_ctx())
    assert md.startswith("# Draft proposal")
    assert mock_llm.call_count == 1
    call = mock_llm.call_args
    # The user message should contain the bundle-shaped context.
    user_message = call.kwargs.get("user_message") or call.args[1]
    assert "Contextual Retrieval" in user_message
    assert "Your hypothesis" in user_message


@patch("backend.research.proposal_render.call_llm_with_fallback")
def test_render_proposal_falls_back_to_bundle_when_llm_fails(mock_llm):
    mock_llm.return_value = None
    md = render_proposal_md(_rich_ctx())
    # Falls back to the bundle
    assert "# Research context — AI clone" in md

"""Tests for backend.research.proposal_context."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.research.proposal_context import (
    MAX_PAPERS,
    MAX_PINNED_INSIGHTS,
    assemble_context,
)


def _mk_card(paper_id: str, title: str, areas=None, digest=None):
    return {
        "paper_id": paper_id,
        "title": title,
        "authors": ["Alice", "Bob"],
        "source": "arxiv",
        "source_url": f"https://arxiv.org/abs/{paper_id}",
        "hook": f"hook for {title}",
        "why_you_now": "matters to you",
        "digest": digest or {"gist": f"{title} gist", "key_ideas": ["idea 1", "idea 2"]},
        "areas_matched": areas or [],
    }


@patch("backend.research.proposal_context.db")
def test_assembles_hypothesis_and_papers(mock_db):
    mock_db.get_full_profile.return_value = {
        "meta": {},
        "areas": [{"id": "a1", "name": "AI clone", "description": "faithful clone"}],
        "hypothesis": {"statement": "Faithful AI clones are possible from a personal corpus."},
        "summaries": [],
    }
    mock_db.get_workspace.return_value = {"name": "Default", "description": ""}
    mock_db.get_user_meta.return_value = {"background": "SDE", "learning_style": "reads-to-build"}
    mock_db.list_feed_cards.return_value = ([_mk_card("p1", "Paper One")], None)
    mock_db.list_all_conversations.return_value = []
    mock_db.list_all_engagement_events.return_value = []

    table = MagicMock()
    table.query.return_value = {"Items": []}

    ctx = assemble_context(table, "u1", "w1")

    assert ctx.hypothesis_statement.startswith("Faithful AI clones")
    assert ctx.background == "SDE"
    assert len(ctx.papers) == 1
    assert ctx.papers[0].title == "Paper One"
    assert ctx.papers[0].digest_gist == "Paper One gist"
    assert ctx.papers[0].key_ideas == ["idea 1", "idea 2"]


@patch("backend.research.proposal_context.db")
def test_area_filter_limits_papers(mock_db):
    mock_db.get_full_profile.return_value = {
        "meta": {},
        "areas": [
            {"id": "clone", "name": "AI clone", "description": ""},
            {"id": "sec", "name": "Security", "description": ""},
        ],
        "hypothesis": {"statement": "H"},
    }
    mock_db.get_workspace.return_value = {"name": "WS"}
    mock_db.get_user_meta.return_value = {}
    mock_db.list_feed_cards.return_value = (
        [
            _mk_card("p1", "In area", areas=["AI clone"]),
            _mk_card("p2", "Off area", areas=["Security"]),
        ],
        None,
    )
    mock_db.list_all_conversations.return_value = []
    mock_db.list_all_engagement_events.return_value = []

    table = MagicMock()
    table.query.return_value = {"Items": []}

    ctx = assemble_context(table, "u1", "w1", area_id="clone")
    assert ctx.area_name == "AI clone"
    titles = [p.title for p in ctx.papers]
    assert "In area" in titles
    assert "Off area" not in titles


@patch("backend.research.proposal_context.db")
def test_paper_cap_and_truncation_note(mock_db):
    mock_db.get_full_profile.return_value = {
        "meta": {}, "areas": [], "hypothesis": None,
    }
    mock_db.get_workspace.return_value = {"name": "WS"}
    mock_db.get_user_meta.return_value = {}
    over = MAX_PAPERS + 5
    mock_db.list_feed_cards.return_value = (
        [_mk_card(f"p{i}", f"Paper {i}") for i in range(over)],
        None,
    )
    mock_db.list_all_conversations.return_value = []
    mock_db.list_all_engagement_events.return_value = []

    table = MagicMock()
    table.query.return_value = {"Items": []}
    ctx = assemble_context(table, "u1", "w1")
    assert len(ctx.papers) == MAX_PAPERS
    assert any(f"{over - MAX_PAPERS} more" in n for n in ctx.truncation_notes)


@patch("backend.research.proposal_context.db")
def test_pinned_insight_cap(mock_db):
    mock_db.get_full_profile.return_value = {"meta": {}, "areas": [], "hypothesis": None}
    mock_db.get_workspace.return_value = {"name": "WS"}
    mock_db.get_user_meta.return_value = {}
    mock_db.list_feed_cards.return_value = ([], None)
    # 3 convs, each with many pinned turns → should cap at MAX_PINNED_INSIGHTS.
    convs = [
        {"conv_id": f"c{i}", "title": f"Conv {i}", "paper_id": f"p{i}"} for i in range(3)
    ]
    mock_db.list_all_conversations.return_value = convs
    mock_db.get_pinned_turns.side_effect = lambda t, u, w, cid: [
        {"request": f"q from {cid}", "response": f"a from {cid}"} for _ in range(10)
    ]
    mock_db.get_conversation_turns.return_value = []
    mock_db.list_all_engagement_events.return_value = []

    table = MagicMock()
    table.query.return_value = {"Items": []}
    ctx = assemble_context(table, "u1", "w1")
    assert len(ctx.pinned_insights) == MAX_PINNED_INSIGHTS
    # total pinned count still reflects the truth (30 across 3 convs)
    assert ctx.engagement.pinned_turns == 30
    assert any("more exist" in n for n in ctx.truncation_notes)


@patch("backend.research.proposal_context.db")
def test_engagement_counts(mock_db):
    mock_db.get_full_profile.return_value = {"meta": {}, "areas": [], "hypothesis": None}
    mock_db.get_workspace.return_value = {"name": "WS"}
    mock_db.get_user_meta.return_value = {}
    mock_db.list_feed_cards.return_value = ([], None)
    mock_db.list_all_conversations.return_value = []
    mock_db.list_all_engagement_events.return_value = [
        {"action": "dismiss"}, {"action": "dismiss"},
        {"action": "bookmark"},
        {"action": "source_click"}, {"action": "source_click"}, {"action": "source_click"},
        {"action": "read_fully"},
        {"action": "bounce"},
    ]

    table = MagicMock()
    ctx = assemble_context(table, "u1", "w1")
    e = ctx.engagement
    assert e.dismissed == 2
    assert e.bookmarked == 1
    assert e.source_clicked == 3
    assert e.read_fully == 1
    assert e.bounced == 1


@patch("backend.research.proposal_context.db")
def test_empty_workspace_still_returns_context(mock_db):
    mock_db.get_full_profile.return_value = {"meta": {}, "areas": [], "hypothesis": None}
    mock_db.get_workspace.return_value = None
    mock_db.get_user_meta.return_value = None
    mock_db.list_feed_cards.return_value = ([], None)
    mock_db.list_all_conversations.return_value = []
    mock_db.list_all_engagement_events.return_value = []

    table = MagicMock()
    table.query.return_value = {"Items": []}
    ctx = assemble_context(table, "u1", "w1")
    assert ctx.hypothesis_statement == ""
    assert ctx.papers == []
    assert ctx.pinned_insights == []
    assert ctx.engagement.dismissed == 0

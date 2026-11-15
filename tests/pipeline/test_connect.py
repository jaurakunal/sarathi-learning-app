"""Tests for backend.pipeline.connect — the Connect pipeline step."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.pipeline import connect


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


NOW = datetime.now(timezone.utc)

GOOD_VERDICT = {
    "connected": True,
    "relation": "contradicts",
    "hook": "Yesterday's consolidation result does not survive longer horizons.",
    "why_it_matters": "Your clone's memory design leans on the earlier result.",
    "claim_a": "Sleep-style consolidation improves recall at 1k turns.",
    "claim_b": "The same consolidation degrades recall beyond 10k turns.",
    "explanation": "B reruns A's setup at longer horizons and finds the gain reverses.",
    "honesty_note": "Different benchmarks; the conflict may be a horizon effect.",
    "question": "At what horizon does the gain flip?",
}


def _hit(paper_id: str, distance: float, key: str = "") -> dict:
    return {
        "key": key or f"{paper_id}:method:0",
        "distance": distance,
        "metadata": {"paper_id": paper_id, "paper_title": f"Title of {paper_id}", "section_name": "method"},
    }


@pytest.fixture
def new_card(sample_feed_cards):
    card = sample_feed_cards[0].copy()
    card["created_at"] = _iso(NOW - timedelta(hours=1))
    card["content_basis"] = "full_text"
    return card


@pytest.fixture
def old_card(sample_feed_cards):
    card = sample_feed_cards[1].copy()
    card["paper_id"] = "paper-old"
    card["card_id"] = "20260501_120000_old00000"
    card["created_at"] = _iso(NOW - timedelta(days=30))
    return card


@pytest.fixture
def env(new_card, old_card):
    """Patch every external dependency of the step; yield the mocks."""
    with patch("backend.pipeline.connect.boto3") as mock_boto3, \
         patch("backend.pipeline.connect.db") as mock_db, \
         patch("backend.pipeline.connect.call_llm_with_fallback") as mock_llm, \
         patch("backend.shared.embeddings.embed_text") as mock_embed, \
         patch("backend.shared.vectors.query_vectors") as mock_query, \
         patch("backend.shared.vectors.get_chunk_texts") as mock_chunks:
        mock_boto3.resource.return_value.Table.return_value = MagicMock()
        mock_db.get_active_workspace.return_value = "ws-1"
        mock_db.list_feed_cards.return_value = ([new_card, old_card], None)
        mock_db.list_all_engagement_events.return_value = [
            {"paper_id": "paper-old", "action": "read"},
        ]
        mock_db.get_full_profile.return_value = {"hypothesis": {"statement": "Harness >> LLM."}}
        mock_db.get_feed_card_by_paper.return_value = old_card
        mock_db.get_pinned_turns.return_value = []
        mock_embed.return_value = [0.1] * 1024
        mock_query.return_value = [_hit("paper-old", 0.2)]
        mock_chunks.return_value = {"paper-old:method:0": "Consolidation improves recall at 1k turns."}
        mock_llm.return_value = json.dumps(GOOD_VERDICT)
        yield {
            "db": mock_db, "llm": mock_llm, "embed": mock_embed,
            "query": mock_query, "chunks": mock_chunks,
        }


EVENT = {"user_id": "user-abc-123", "workspace_id": "ws-1", "table_name": "sarathi-test-table"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_writes_connect_card(env, new_card, old_card):
    result = connect.handler(EVENT, None)

    assert result["connect_cards"] == 1
    env["db"].put_feed_card.assert_called_once()
    card = env["db"].put_feed_card.call_args[0][3]

    assert card["card_type"] == "connect"
    assert card["paper_id"] == new_card["paper_id"]  # anchored to the new paper
    assert card["full_text_s3_key"] == new_card["full_text_s3_key"]
    assert card["hook"] == GOOD_VERDICT["hook"]
    assert card["digest"]["gist"] == GOOD_VERDICT["explanation"]
    assert card["suggested_questions"] == [GOOD_VERDICT["question"]]

    conn = card["connection"]
    assert conn["relation"] == "contradicts"
    assert conn["new"]["card_id"] == new_card["card_id"]
    assert conn["new"]["claim"] == GOOD_VERDICT["claim_b"]
    assert conn["related"]["paper_id"] == "paper-old"
    assert conn["related"]["card_id"] == old_card["card_id"]
    assert conn["related"]["claim"] == GOOD_VERDICT["claim_a"]


def test_vector_query_is_scoped_to_library_excluding_new_papers(env, new_card):
    env["db"].list_all_engagement_events.return_value = [
        {"paper_id": "paper-old", "action": "bookmark"},
        {"paper_id": "paper-rated", "action": "rate", "rating": 5},
        {"paper_id": "paper-meh", "action": "rate", "rating": 2},
        {"paper_id": "paper-seen", "action": "impression"},
        {"paper_id": new_card["paper_id"], "action": "read"},  # today's own paper
    ]
    connect.handler(EVENT, None)

    kwargs = env["query"].call_args.kwargs
    assert kwargs["paper_ids"] == {"paper-old", "paper-rated"}
    assert kwargs["return_distance"] is True


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def test_no_card_when_library_empty(env):
    env["db"].list_all_engagement_events.return_value = [
        {"paper_id": "paper-old", "action": "impression"},
    ]
    result = connect.handler(EVENT, None)
    assert result == {"connect_cards": 0, "reason": "empty_library"}
    env["llm"].assert_not_called()


def test_no_card_when_nothing_close_enough(env):
    env["query"].return_value = [_hit("paper-old", connect.MAX_DISTANCE + 0.1)]
    result = connect.handler(EVENT, None)
    assert result["connect_cards"] == 0
    assert result["reason"] == "no_close_match"
    env["llm"].assert_not_called()


@pytest.mark.parametrize("response", [
    json.dumps({"connected": False, "relation": "none"}),
    json.dumps({**GOOD_VERDICT, "relation": "related"}),       # not a real relation
    json.dumps({**GOOD_VERDICT, "claim_a": ""}),               # no named claim
    "these papers are both about memory",                     # not JSON
    None,                                                      # LLM failed
])
def test_llm_gate_rejects(env, response):
    env["llm"].return_value = response
    result = connect.handler(EVENT, None)
    assert result["connect_cards"] == 0
    env["db"].put_feed_card.assert_not_called()


def test_accepts_fenced_json(env):
    env["llm"].return_value = "```json\n" + json.dumps(GOOD_VERDICT) + "\n```"
    assert connect.handler(EVENT, None)["connect_cards"] == 1


def test_weekly_cap(env, new_card, old_card):
    recent = [
        {"card_id": f"c{i}", "card_type": "connect", "created_at": _iso(NOW - timedelta(days=i + 1)),
         "connection": {"new": {"paper_id": f"n{i}"}, "related": {"paper_id": f"o{i}"}}}
        for i in range(connect.MAX_PER_WEEK)
    ]
    env["db"].list_feed_cards.return_value = ([new_card, old_card, *recent], None)
    result = connect.handler(EVENT, None)
    assert result == {"connect_cards": 0, "reason": "weekly_cap"}
    env["embed"].assert_not_called()


def test_same_pair_not_connected_twice(env, new_card, old_card):
    earlier = {
        "card_id": "c-old", "card_type": "connect", "created_at": _iso(NOW - timedelta(days=20)),
        "connection": {"new": {"paper_id": new_card["paper_id"]}, "related": {"paper_id": "paper-old"}},
    }
    env["db"].list_feed_cards.return_value = ([new_card, old_card, earlier], None)
    result = connect.handler(EVENT, None)
    assert result["connect_cards"] == 0
    env["llm"].assert_not_called()


def test_abstract_only_and_stale_cards_are_not_sources(env, new_card, old_card):
    abstract_only = {**new_card, "content_basis": "abstract"}
    env["db"].list_feed_cards.return_value = ([abstract_only, old_card], None)
    assert connect.handler(EVENT, None) == {"connect_cards": 0, "reason": "no_new_cards"}


def test_per_run_cap_takes_closest_pair_first(env, new_card, old_card):
    second = {**new_card, "card_id": "20260607_130000_second00", "paper_id": "paper-new-2"}
    env["db"].list_feed_cards.return_value = ([new_card, second, old_card], None)
    env["db"].list_all_engagement_events.return_value = [
        {"paper_id": "paper-old", "action": "read"},
        {"paper_id": "paper-old-2", "action": "read"},
    ]
    # first new card → far match, second new card → near match
    env["query"].side_effect = [[_hit("paper-old", 0.5)], [_hit("paper-old-2", 0.1)]]

    result = connect.handler(EVENT, None)

    assert result["connect_cards"] == 1  # MAX_PER_RUN default
    card = env["db"].put_feed_card.call_args[0][3]
    assert card["paper_id"] == "paper-new-2"
    assert card["connection"]["related"]["paper_id"] == "paper-old-2"
    assert env["llm"].call_count == 1


def test_never_raises(env):
    env["db"].list_feed_cards.side_effect = RuntimeError("ddb down")
    result = connect.handler(EVENT, None)
    assert result["connect_cards"] == 0
    assert result["error"] == "exception"


# ---------------------------------------------------------------------------
# Unit: match collapsing
# ---------------------------------------------------------------------------

def test_best_match_picks_closest_paper_and_its_top_sections():
    hits = [
        _hit("p1", 0.30, "p1:intro:0"),
        _hit("p2", 0.10, "p2:method:1"),
        _hit("p2", 0.25, "p2:results:2"),
        _hit("p2", 0.40, "p2:intro:0"),
        _hit("p3", 0.90, "p3:intro:0"),
        {"key": "no-distance", "metadata": {"paper_id": "p4"}},
    ]
    best = connect._best_match(hits, 0.6)
    assert best["paper_id"] == "p2"
    assert best["distance"] == 0.10
    assert best["keys"] == ["p2:method:1", "p2:results:2"]
    assert connect._best_match(hits, 0.05) is None

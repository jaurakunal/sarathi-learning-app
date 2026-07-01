"""Tests for the Learn pipeline step."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.pipeline.learn import handler, _aggregate_engagement, _build_learn_prompt


class TestAggregateEngagement:
    def test_counts_read_papers(self):
        events = [
            {"action": "read", "paper_id": "p1", "active_ms": 30000, "scroll_depth_pct": 80},
            {"action": "read", "paper_id": "p2", "active_ms": 20000, "scroll_depth_pct": 60},
        ]
        stats = _aggregate_engagement(events)
        assert set(stats["papers_read"]) == {"p1", "p2"}
        assert stats["total_active_ms"] == 50000
        assert stats["avg_scroll_depth"] == 70

    def test_counts_dismissed_papers(self):
        events = [
            {"action": "dismiss", "paper_id": "p1"},
            {"action": "dismiss", "paper_id": "p2"},
            {"action": "dismiss", "paper_id": "p1"},  # duplicate
        ]
        stats = _aggregate_engagement(events)
        assert set(stats["papers_dismissed"]) == {"p1", "p2"}

    def test_counts_sections_expanded(self):
        events = [
            {"action": "expand", "paper_id": "p1", "section": "glossary"},
            {"action": "expand", "paper_id": "p1", "section": "deep_dive"},
            {"action": "expand", "paper_id": "p2", "section": "deep_dive"},
            {"action": "expand", "paper_id": "p2", "section": "math_notes"},
        ]
        stats = _aggregate_engagement(events)
        assert stats["sections_expanded"]["glossary"] == 1
        assert stats["sections_expanded"]["deep_dive"] == 2
        assert stats["sections_expanded"]["math_notes"] == 1

    def test_counts_ratings(self):
        events = [
            {"action": "rate", "paper_id": "p1", "rating": 5},
            {"action": "rate", "paper_id": "p2", "rating": 1},
            {"action": "rate", "paper_id": "p3", "rating": 5},
        ]
        stats = _aggregate_engagement(events)
        assert set(stats["papers_rated_up"]) == {"p1", "p3"}
        assert stats["papers_rated_down"] == ["p2"]

    def test_counts_impressions_and_views(self):
        events = [
            {"action": "impression", "paper_id": "p1"},
            {"action": "impression", "paper_id": "p2"},
            {"action": "view", "paper_id": "p1"},
        ]
        stats = _aggregate_engagement(events)
        assert stats["impressions"] == 2
        assert stats["views"] == 1

    def test_empty_events(self):
        stats = _aggregate_engagement([])
        assert stats["total_events"] == 0
        assert stats["papers_read"] == []


class TestBuildLearnPrompt:
    def test_includes_profile_areas(self):
        profile = {
            "meta": {"learning_style": {}, "reading_speed": "medium"},
            "areas": [{"id": "area1", "name": "Memory", "status": "hot", "frontier": "Knows RAG basics"}],
            "hypothesis": {"statement": "Brain structure > LLM", "supporting": [], "refuting": []},
        }
        prompt = _build_learn_prompt(profile, _aggregate_engagement([]), [])
        assert "Memory" in prompt
        assert "Knows RAG basics" in prompt
        assert "Brain structure > LLM" in prompt

    def test_includes_engagement_stats(self):
        events = [{"action": "read", "paper_id": "p1", "active_ms": 30000, "scroll_depth_pct": 80}]
        stats = _aggregate_engagement(events)
        prompt = _build_learn_prompt({"meta": {}, "areas": []}, stats, [])
        assert "p1" in prompt
        assert "30000ms" in prompt

    def test_includes_conversations(self):
        convos = [{"paper_id": "p1", "turns": [{"question": "What is reflection?", "answer": "It means..."}]}]
        prompt = _build_learn_prompt({"meta": {}, "areas": []}, _aggregate_engagement([]), convos)
        assert "What is reflection?" in prompt
        assert "It means..." in prompt

    def test_no_conversations(self):
        prompt = _build_learn_prompt({"meta": {}, "areas": []}, _aggregate_engagement([]), [])
        assert "No new conversations" in prompt


class TestHandler:
    @patch("backend.pipeline.learn.boto3")
    @patch("backend.pipeline.learn.db")
    def test_skips_when_no_profile(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_active_workspace.return_value = ""
        mock_db.get_full_profile.return_value = {"meta": None, "areas": [], "hypothesis": None, "summaries": []}

        result = handler({"user_id": "u1", "table_name": "t"}, None)
        assert result["status"] == "skipped"

    @patch("backend.pipeline.learn.boto3")
    @patch("backend.pipeline.learn.db")
    def test_skips_when_no_activity(self, mock_db, mock_boto3):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_active_workspace.return_value = ""
        mock_db.get_full_profile.return_value = {
            "meta": {"last_learn_ts": "2026-06-18T00:00:00Z"},
            "areas": [],
            "hypothesis": None,
            "summaries": [],
        }
        mock_db.list_engagement_events.return_value = []
        mock_table.query.return_value = {"Items": []}  # no conversations

        result = handler({"user_id": "u1", "table_name": "t"}, None)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_activity"

    @patch("backend.pipeline.learn.call_llm")
    @patch("backend.pipeline.learn.boto3")
    @patch("backend.pipeline.learn.db")
    def test_successful_learn_updates_profile(self, mock_db, mock_boto3, mock_llm):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_active_workspace.return_value = ""
        mock_db.get_full_profile.return_value = {
            "meta": {"last_learn_ts": "2026-06-18T00:00:00Z"},
            "areas": [{"id": "memory", "name": "Memory", "status": "warm", "frontier": "Knows RAG"}],
            "hypothesis": {"statement": "Brain > LLM", "supporting": [], "refuting": []},
            "summaries": [],
        }
        mock_db.list_engagement_events.return_value = [
            {"action": "read", "paper_id": "p1", "active_ms": 30000, "scroll_depth_pct": 80},
        ]
        mock_table.query.return_value = {"Items": []}  # no conversations via GSI1

        mock_llm.return_value = json.dumps({
            "areas": [{"area_id": "memory", "frontier": "Understands reflection + memory streams", "status": "hot"}],
            "hypothesis_evidence": {"supporting": ["Paper p1 shows architecture dominates"]},
            "summaries": {"yesterday": "Read a memory paper", "three_day": "Active on memory", "seven_day": "Deep in memory week", "month": "Month of memory", "quarter": "Quarter summary"},
            "changelog": "Memory area upgraded to hot. Frontier advanced.",
        })

        result = handler({"user_id": "u1", "table_name": "t"}, None)

        assert result["status"] == "ok"
        assert "area:memory" in result["changes"]
        assert "hypothesis" in result["changes"]
        assert "summaries" in result["changes"]
        mock_db.put_profile_area.assert_called_once()
        mock_db.put_profile_hypothesis.assert_called_once()
        mock_db.put_profile_meta.assert_called_once()
        mock_db.put_profile_history_event.assert_called_once()

    @patch("backend.pipeline.learn.call_llm")
    @patch("backend.pipeline.learn.boto3")
    @patch("backend.pipeline.learn.db")
    def test_handles_llm_failure(self, mock_db, mock_boto3, mock_llm):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_active_workspace.return_value = ""
        mock_db.get_full_profile.return_value = {
            "meta": {"last_learn_ts": "2026-06-18T00:00:00Z"},
            "areas": [],
            "hypothesis": None,
            "summaries": [],
        }
        mock_db.list_engagement_events.return_value = [{"action": "read", "paper_id": "p1"}]
        mock_table.query.return_value = {"Items": []}
        mock_llm.return_value = None

        result = handler({"user_id": "u1", "table_name": "t"}, None)
        assert result["status"] == "error"
        assert result["reason"] == "llm_failed"

    @patch("backend.pipeline.learn.call_llm")
    @patch("backend.pipeline.learn.boto3")
    @patch("backend.pipeline.learn.db")
    def test_handles_invalid_json_response(self, mock_db, mock_boto3, mock_llm):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_active_workspace.return_value = ""
        mock_db.get_full_profile.return_value = {
            "meta": {"last_learn_ts": "2026-06-18T00:00:00Z"},
            "areas": [],
            "hypothesis": None,
            "summaries": [],
        }
        mock_db.list_engagement_events.return_value = [{"action": "read", "paper_id": "p1"}]
        mock_table.query.return_value = {"Items": []}
        mock_llm.return_value = "This is not JSON at all"

        result = handler({"user_id": "u1", "table_name": "t"}, None)
        assert result["status"] == "error"
        assert result["reason"] == "parse_failed"

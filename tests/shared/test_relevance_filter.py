"""Unit tests for backend.shared.relevance_filter."""

from unittest.mock import patch

import pytest

from backend.shared.models import Area
from backend.shared.relevance_filter import batch_relevance_filter


@pytest.fixture
def sample_areas():
    return [
        Area(id="a1", user_id="u1", label="agent memory", just_right=["reflection", "memory stream"]),
        Area(id="a2", user_id="u1", label="person cloning", just_right=["persona simulation"]),
    ]


@pytest.fixture
def sample_papers():
    return [
        {"title": "Memory Stream Architecture for LLM Agents", "abstract": "We propose..."},
        {"title": "Photosynthesis in Alpine Plants", "abstract": "A biology study..."},
        {"title": "Generative Agents Simulate Human Behavior", "abstract": "Agent memory..."},
        {"title": "Quantum Computing Error Correction", "abstract": "We present a novel..."},
        {"title": "Persona Cloning via Language Models", "abstract": "We clone..."},
    ]


class TestBatchRelevanceFilter:
    @patch("backend.shared.relevance_filter.call_llm")
    def test_happy_path_filters_irrelevant(self, mock_llm, sample_areas, sample_papers):
        """LLM returns indices of relevant papers, irrelevant ones are filtered."""
        mock_llm.return_value = "[0, 2, 4]"
        result = batch_relevance_filter(sample_papers, sample_areas)
        assert len(result) == 3
        assert result[0]["title"] == "Memory Stream Architecture for LLM Agents"
        assert result[1]["title"] == "Generative Agents Simulate Human Behavior"
        assert result[2]["title"] == "Persona Cloning via Language Models"

    @patch("backend.shared.relevance_filter.call_llm")
    def test_llm_failure_returns_all_papers(self, mock_llm, sample_areas, sample_papers):
        """On LLM failure (None), fail-open: return all papers."""
        mock_llm.return_value = None
        result = batch_relevance_filter(sample_papers, sample_areas)
        assert len(result) == 5

    @patch("backend.shared.relevance_filter.call_llm")
    def test_malformed_json_returns_all(self, mock_llm, sample_areas, sample_papers):
        """Malformed LLM response: fail-open."""
        mock_llm.return_value = "not valid json"
        result = batch_relevance_filter(sample_papers, sample_areas)
        assert len(result) == 5

    @patch("backend.shared.relevance_filter.call_llm")
    def test_markdown_fenced_json(self, mock_llm, sample_areas, sample_papers):
        """Handle markdown-fenced JSON response."""
        mock_llm.return_value = "```json\n[0, 2, 4]\n```"
        result = batch_relevance_filter(sample_papers, sample_areas)
        assert len(result) == 3

    @patch("backend.shared.relevance_filter.call_llm")
    def test_out_of_range_indices_ignored(self, mock_llm, sample_areas, sample_papers):
        """Indices out of range are silently dropped."""
        mock_llm.return_value = "[0, 2, 99, -1, 4]"
        result = batch_relevance_filter(sample_papers, sample_areas)
        assert len(result) == 3

    @patch("backend.shared.relevance_filter.call_llm")
    def test_empty_papers_returns_empty(self, mock_llm, sample_areas):
        """Empty input returns empty output."""
        result = batch_relevance_filter([], sample_areas)
        assert result == []
        mock_llm.assert_not_called()

    @patch("backend.shared.relevance_filter.call_llm")
    def test_three_or_fewer_papers_skip_filter(self, mock_llm, sample_areas):
        """3 or fewer papers skip the LLM call entirely (not worth filtering)."""
        papers = [{"title": "A", "abstract": "a"}, {"title": "B", "abstract": "b"}]
        result = batch_relevance_filter(papers, sample_areas)
        assert len(result) == 2
        mock_llm.assert_not_called()

    @patch("backend.shared.relevance_filter.call_llm")
    def test_all_relevant(self, mock_llm, sample_areas, sample_papers):
        """LLM says all papers are relevant."""
        mock_llm.return_value = "[0, 1, 2, 3, 4]"
        result = batch_relevance_filter(sample_papers, sample_areas)
        assert len(result) == 5

    @patch("backend.shared.relevance_filter.call_llm")
    def test_none_relevant(self, mock_llm, sample_areas, sample_papers):
        """LLM says no papers are relevant."""
        mock_llm.return_value = "[]"
        result = batch_relevance_filter(sample_papers, sample_areas)
        assert len(result) == 0

"""Shared fixtures for pipeline step tests.

Mocks external modules (anthropic, arxiv, etc.) so tests run even without
those packages installed.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Pre-import mocking: inject mock modules for dependencies that may not be
# installed in the test environment. This must happen before any pipeline
# module imports.
# ---------------------------------------------------------------------------

# Mock the anthropic module
_mock_anthropic = MagicMock()
_mock_anthropic.APIError = type("APIError", (Exception,), {})
_mock_anthropic.APIStatusError = type(
    "APIStatusError",
    (_mock_anthropic.APIError,),
    {"__init__": lambda self, *a, **kw: Exception.__init__(self, kw.get("message", ""))},
)
sys.modules.setdefault("anthropic", _mock_anthropic)

# Mock arxiv module (used by backend.sources.arxiv)
sys.modules.setdefault("arxiv", MagicMock())

# Mock feedparser (used by sources)
sys.modules.setdefault("feedparser", MagicMock())

# Mock requests (used by sources)
sys.modules.setdefault("requests", MagicMock())

# Mock openreview (if used)
sys.modules.setdefault("openreview", MagicMock())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id():
    """Standard test user ID (Cognito sub)."""
    return "user-abc-123"


@pytest.fixture
def table_name():
    """Standard test DDB table name."""
    return "sarathi-test-table"


@pytest.fixture
def mock_table():
    """A MagicMock standing in for a boto3 DynamoDB Table resource."""
    return MagicMock()


@pytest.fixture
def sample_profile():
    """A fully-populated user profile dict as returned by db.get_full_profile."""
    return {
        "meta": {
            "learning_style": {
                "math": "route-around; tap-to-reveal only; never gate",
                "lead_with": "applied / can-I-use-this",
                "tone": "sharp mirror, no flattery, credit at exact scope",
            },
            "paper_goal": "Accumulate citations/claims/gaps toward my own paper.",
        },
        "areas": [
            {
                "id": "area-1",
                "user_id": "user-abc-123",
                "label": "Memory Architecture",
                "status": "active",
                "role": "spine",
                "links": [],
                "frontier": "episodic memory retrieval for agents",
                "too_basic": ["RAG", "vector databases"],
                "just_right": ["episodic memory", "memory consolidation"],
                "added_at": "2026-06-01T00:00:00Z",
            },
            {
                "id": "area-2",
                "user_id": "user-abc-123",
                "label": "Agentic Harness",
                "status": "active",
                "role": "secondary",
                "links": [],
                "frontier": "tool-use reliability under ambiguity",
                "too_basic": ["function calling"],
                "just_right": ["tool-use planning", "multi-step reasoning"],
                "added_at": "2026-06-01T00:00:00Z",
            },
        ],
        "hypothesis": {
            "statement": "Brain-structure + agentic harness >> the LLM.",
            "status": "untested",
            "supporting": [],
            "refuting": [],
            "refining": [],
        },
        "summaries": [],
    }


@pytest.fixture
def sample_papers():
    """A list of sample paper dicts as would come from a source or DDB."""
    return [
        {
            "id": "paper-001",
            "source": "arxiv",
            "title": "Episodic Memory for LLM Agents",
            "authors": ["Smith, A.", "Jones, B."],
            "abstract": "We propose a new memory architecture for LLM agents...",
            "url": "https://arxiv.org/abs/2406.00001",
            "published": "2026-06-05",
            "status": "candidate",
            "triage_score": 0,
            "worth_my_hours": False,
            "discovered_at": "2026-06-07T12:00:00Z",
            "arxiv_categories": ["cs.AI"],
            "fields_of_study": [],
            "citation_count": 0,
            "influential_citation_count": 0,
            "upvotes": 0,
            "venue": "",
            "peer_review_score": None,
        },
        {
            "id": "paper-002",
            "source": "semantic_scholar",
            "title": "Tool Use Planning Under Uncertainty",
            "authors": ["Lee, C."],
            "abstract": "This paper studies how agents plan tool use...",
            "url": "https://semanticscholar.org/paper/002",
            "published": "2026-06-03",
            "status": "candidate",
            "triage_score": 0,
            "worth_my_hours": False,
            "discovered_at": "2026-06-07T12:00:00Z",
            "arxiv_categories": [],
            "fields_of_study": ["Computer Science"],
            "citation_count": 5,
            "influential_citation_count": 1,
            "upvotes": 0,
            "venue": "NeurIPS",
            "peer_review_score": None,
        },
        {
            "id": "paper-003",
            "source": "hf_daily_papers",
            "title": "A Survey on Retrieval-Augmented Generation",
            "authors": ["Zhang, D.", "Wang, E."],
            "abstract": "RAG has become the dominant paradigm...",
            "url": "https://huggingface.co/papers/003",
            "published": "2026-06-04",
            "status": "candidate",
            "triage_score": 0,
            "worth_my_hours": False,
            "discovered_at": "2026-06-07T12:00:00Z",
            "arxiv_categories": [],
            "fields_of_study": [],
            "citation_count": 0,
            "influential_citation_count": 0,
            "upvotes": 42,
            "venue": "",
            "peer_review_score": None,
        },
    ]


@pytest.fixture
def sample_surfaced_papers():
    """Papers that have been promoted to 'surfaced' status with triage scores."""
    return [
        {
            "id": "paper-001",
            "source": "arxiv",
            "title": "Episodic Memory for LLM Agents",
            "authors": ["Smith, A.", "Jones, B."],
            "abstract": "We propose a new memory architecture...",
            "url": "https://arxiv.org/abs/2406.00001",
            "published": "2026-06-05",
            "status": "surfaced",
            "triage_score": 0.92,
            "worth_my_hours": True,
            "discovered_at": "2026-06-07T12:00:00Z",
        },
        {
            "id": "paper-002",
            "source": "semantic_scholar",
            "title": "Tool Use Planning Under Uncertainty",
            "authors": ["Lee, C."],
            "abstract": "This paper studies how agents plan tool use...",
            "url": "https://semanticscholar.org/paper/002",
            "published": "2026-06-03",
            "status": "surfaced",
            "triage_score": 0.85,
            "worth_my_hours": True,
            "discovered_at": "2026-06-07T12:00:00Z",
        },
        {
            "id": "paper-003",
            "source": "hf_daily_papers",
            "title": "Harness Design Patterns",
            "authors": ["Zhang, D."],
            "abstract": "Design patterns for agentic harnesses...",
            "url": "https://huggingface.co/papers/003",
            "published": "2026-06-04",
            "status": "surfaced",
            "triage_score": 0.78,
            "worth_my_hours": True,
            "discovered_at": "2026-06-07T12:00:00Z",
        },
    ]


@pytest.fixture
def sample_feed_cards():
    """Sample feed cards as stored in DDB."""
    return [
        {
            "card_id": "20260607_120000_abcd1234",
            "paper_id": "paper-001",
            "source_url": "https://arxiv.org/abs/2406.00001",
            "full_text_s3_key": "users/user-abc-123/papers/paper-001/full_text.txt",
            "card_type": "new_paper",
            "hook": "What if your agent could remember last Tuesday?",
            "why_you_now": "Your clone needs episodic memory to be faithful.",
            "time_estimate": "12 min",
            "digest": {
                "gist": "A new architecture for episodic memory in agents.",
                "key_ideas": [
                    "Agents need time-aware memory retrieval",
                    "Consolidation mimics human sleep cycles",
                ],
                "deep": "The paper proposes...",
            },
            "glossary": [{"term": "episodic memory", "plain": "Memory of specific events"}],
            "math_notes": [],
            "hypothesis_relevance": "",
            "honesty_note": "Full read recommended — directly on your frontier.",
            "suggested_questions": ["How would this plug into my harness?"],
        },
        {
            "card_id": "20260607_120100_efgh5678",
            "paper_id": "paper-002",
            "source_url": "https://semanticscholar.org/paper/002",
            "full_text_s3_key": "users/user-abc-123/papers/paper-002/full_text.txt",
            "card_type": "new_paper",
            "hook": "Planning tool calls when you can't predict what will break.",
            "why_you_now": "Your harness fails on ambiguous tool selections.",
            "time_estimate": "8 min",
            "digest": {
                "gist": "How agents plan tool use under uncertainty.",
                "key_ideas": ["Uncertainty quantification for tool selection"],
                "deep": "The authors develop...",
            },
            "glossary": [],
            "math_notes": [],
            "hypothesis_relevance": "Supports: better harness planning >> raw LLM capability.",
            "honesty_note": "Skim the key ideas, skip the proofs.",
            "suggested_questions": ["Can I apply this to my tool-use agent?"],
        },
    ]

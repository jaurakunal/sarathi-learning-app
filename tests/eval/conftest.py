"""Shared fixtures for eval tests.

Mocks heavyweight deps so tests run with no AWS credentials.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


# Mock optional source-side deps that backend.pipeline.digest imports through
# backend.sources at module load.
sys.modules.setdefault("arxiv", MagicMock())
sys.modules.setdefault("feedparser", MagicMock())
sys.modules.setdefault("openreview", MagicMock())


# ---------------------------------------------------------------------------
# In-memory DDB stub: just enough to satisfy our eval module's queries.
# We mimic put_item / get_item / query / scan / batch_writer.
# ---------------------------------------------------------------------------


class _BatchWriter:
    def __init__(self, table):
        self._table = table

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def put_item(self, Item):
        self._table.put_item(Item=Item)

    def delete_item(self, Key):
        self._table.delete_item(Key=Key)


class FakeTable:
    """Minimal in-memory DDB Table substitute keyed by (PK, SK)."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    # --- writes
    def put_item(self, Item):
        self.items[(Item["PK"], Item["SK"])] = dict(Item)

    def update_item(self, **kwargs):
        # No-op for tests; the eval modules don't rely on update_item.
        return None

    def delete_item(self, Key):
        self.items.pop((Key["PK"], Key["SK"]), None)

    def batch_writer(self):
        return _BatchWriter(self)

    # --- reads
    def get_item(self, Key, **_):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item else {}

    def query(self, **kwargs):
        """Support PK eq + SK begins_with / between / eq, plus IndexName=GSI4 by gsi4pk."""
        kc = kwargs.get("KeyConditionExpression")
        index = kwargs.get("IndexName")

        # Render the condition into something testable. Boto's condition objects
        # expose .get_expression() which we won't use — instead, our tests pass
        # in conditions via the boto3.dynamodb.conditions.Key API and we
        # recover the targeted values from the rendered expression.
        # For the FakeTable we cheat: we re-implement filtering by inspecting
        # the expression via private attributes only present in boto3.
        from boto3.dynamodb.conditions import And, Key  # type: ignore

        items_iter = list(self.items.values())

        # Walk the expression tree for Key("PK").eq(...) / Key("SK").begins_with(...)
        pk_eq = None
        sk_begins = None
        sk_between: tuple | None = None
        sk_eq = None
        gsi_pk_eq = None

        def _walk(expr):
            nonlocal pk_eq, sk_begins, sk_between, sk_eq, gsi_pk_eq
            if isinstance(expr, And):
                for v in expr._values:  # boto exposes _values
                    _walk(v)
                return
            # Conditions expose .get_expression()
            try:
                d = expr.get_expression()
            except AttributeError:
                return
            fmt = d.get("format", "")
            op = d.get("operator", "")
            values = d.get("values", [])
            attr = values[0]
            attr_name = getattr(attr, "name", None)
            if fmt == "{0} {operator} {1}":
                rhs = values[1]
                if attr_name == "PK" and op == "=":
                    pk_eq = rhs
                elif attr_name == "SK" and op == "=":
                    sk_eq = rhs
                elif attr_name == "gsi4pk" and op == "=":
                    gsi_pk_eq = rhs
                elif attr_name == "gsi2pk" and op == "=":
                    gsi_pk_eq = rhs
                elif attr_name == "gsi1pk" and op == "=":
                    gsi_pk_eq = rhs
            elif op == "begins_with":
                rhs = values[1]
                if attr_name == "SK":
                    sk_begins = rhs
            elif op == "BETWEEN":
                sk_between = (values[1], values[2])

        _walk(kc)

        out = []
        for item in items_iter:
            if index in (None, "GSI2", "GSI4", "GSI1"):
                if index is None:
                    if pk_eq is not None and item.get("PK") != pk_eq:
                        continue
                else:
                    gsi_pk_field = {"GSI1": "gsi1pk", "GSI2": "gsi2pk", "GSI4": "gsi4pk"}[index]
                    if gsi_pk_eq is not None and item.get(gsi_pk_field) != gsi_pk_eq:
                        continue
            if sk_begins is not None and not str(item.get("SK", "")).startswith(sk_begins):
                continue
            if sk_eq is not None and item.get("SK") != sk_eq:
                continue
            if sk_between is not None:
                lo, hi = sk_between
                sk = item.get("SK", "")
                if not (lo <= sk <= hi):
                    continue
            out.append(dict(item))
        return {"Items": out}

    def scan(self, **kwargs):
        # FilterExpression with begins_with/eq on PK/SK — we approximate.
        from boto3.dynamodb.conditions import And, Or
        fe = kwargs.get("FilterExpression")

        def _matches(item, expr) -> bool:
            if isinstance(expr, And):
                return all(_matches(item, v) for v in expr._values)
            if isinstance(expr, Or):
                return any(_matches(item, v) for v in expr._values)
            try:
                d = expr.get_expression()
            except AttributeError:
                return True
            fmt = d.get("format", "")
            op = d.get("operator", "")
            values = d.get("values", [])
            attr = values[0]
            attr_name = getattr(attr, "name", None)
            field_val = item.get(attr_name, "")
            if fmt == "{0} {operator} {1}":
                rhs = values[1]
                if op == "=":
                    return field_val == rhs
            elif op == "begins_with":
                rhs = values[1]
                return str(field_val).startswith(str(rhs))
            return True

        out = []
        for item in self.items.values():
            if fe is None or _matches(item, fe):
                out.append(dict(item))
        return {"Items": out}


@pytest.fixture
def fake_table():
    return FakeTable()


@pytest.fixture
def sample_paper():
    return {
        "id": "paper-eval-001",
        "title": "Episodic Memory for LLM Agents",
        "authors": ["Smith, A.", "Jones, B."],
        "abstract": "We propose a new memory architecture for agents.",
        "url": "https://arxiv.org/abs/2406.00001",
        "source": "arxiv",
        "published": "2026-06-05",
        "status": "digested",
        "discovered_at": "2026-06-07T12:00:00Z",
    }


@pytest.fixture
def sample_golden_card():
    return {
        "card_id": "20260607_120000_aaaaaaaa",
        "paper_id": "paper-eval-001",
        "full_text_s3_key": "users/live-user/papers/paper-eval-001/full_text.txt",
        "card_type": "new_paper",
        "hook": "What if your agent could remember last Tuesday?",
        "why_you_now": "Your clone needs episodic memory to be faithful.",
        "time_estimate": "12 min",
        "digest": {
            "gist": "A new architecture for episodic memory in agents.",
            "key_ideas": ["Time-aware retrieval"],
            "deep": "The paper proposes...",
        },
        "glossary": [{"term": "episodic memory", "plain": "Memory of specific events"}],
        "math_notes": [],
        "hypothesis_relevance": "Supports.",
        "honesty_note": "Full read recommended.",
        "suggested_questions": ["How would this plug into my harness?"],
    }


@pytest.fixture
def sample_engagement_events():
    return [
        {"action": "view", "ts": "2026-06-08T10:00:00Z", "paper_id": "paper-eval-001"},
        {"action": "read", "ts": "2026-06-08T10:01:00Z", "paper_id": "paper-eval-001"},
        {"action": "bookmark", "ts": "2026-06-08T10:05:00Z", "paper_id": "paper-eval-001"},
    ]


@pytest.fixture
def sample_profile():
    return {
        "meta": {
            "learning_style": {"math": "route-around", "lead_with": "applied"},
            "paper_goal": "Faithful clones.",
        },
        "areas": [
            {
                "id": "area-1",
                "label": "Memory Architecture",
                "role": "spine",
                "status": "active",
                "frontier": "episodic memory for agents",
                "just_right": ["episodic memory"],
                "too_basic": ["RAG"],
            },
        ],
        "hypothesis": {"statement": "Architecture > LLM size."},
        "summaries": [],
    }

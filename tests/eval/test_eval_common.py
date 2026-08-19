"""Tests for the shared eval data-access helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.eval.eval_common import as_float, resolve_sub, engagement_by_paper


def test_as_float():
    assert as_float("1.5") == 1.5
    assert as_float(None) == 0.0
    assert as_float("nope", default=-1.0) == -1.0
    from decimal import Decimal
    assert as_float(Decimal("2")) == 2.0


def test_resolve_sub_passthrough_for_sub():
    # A raw sub (no @) is returned unchanged, no Cognito call.
    assert resolve_sub("abc-123-sub") == "abc-123-sub"


@patch("backend.eval.eval_common.boto3")
def test_resolve_sub_email_lookup(mock_boto3):
    mock_boto3.client.return_value.list_users.return_value = {
        "Users": [{"Username": "sub-xyz"}]
    }
    assert resolve_sub("a@b.com") == "sub-xyz"


@patch("backend.eval.eval_common.boto3")
def test_resolve_sub_email_not_found_raises(mock_boto3):
    mock_boto3.client.return_value.list_users.return_value = {"Users": []}
    import pytest
    with pytest.raises(SystemExit):
        resolve_sub("missing@b.com")


@patch("backend.eval.eval_common.db")
def test_engagement_by_paper_groups_and_maxes(mock_db):
    mock_db.list_all_engagement_events.return_value = [
        {"paper_id": "p1", "action": "view", "active_ms": 1000},
        {"paper_id": "p1", "action": "read", "active_ms": 5000, "rating": 4},
        {"paper_id": "p2", "action": "dismiss"},
        {"action": "read"},  # no paper_id -> ignored
    ]
    out = engagement_by_paper(MagicMock(), "u1", "w1")
    assert set(out["p1"]["actions"]) == {"view", "read"}
    assert out["p1"]["active_ms"] == 5000   # max, not sum
    assert out["p1"]["rating"] == 4
    assert out["p2"]["actions"] == ["dismiss"]
    assert "" not in out

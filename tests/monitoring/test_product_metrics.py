"""Tests for the daily product-metrics aggregator."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _mk_snap(day, ids):
    return {"day": day, "active_user_ids": ids}


@patch("backend.monitoring.product_metrics.db")
def test_rolling_active_unions_distinct_users(mock_db):
    from backend.monitoring.product_metrics import _rolling_active
    # prior snapshots: same user active multiple days shouldn't double-count
    mock_db.list_metrics_snapshots.return_value = [
        _mk_snap("2026-08-15", ["u1"]),
        _mk_snap("2026-08-16", ["u1", "u2"]),
        _mk_snap("2026-08-17", ["u3"]),
    ]
    wau, mau = _rolling_active(MagicMock(), "2026-08-18", {"u1", "u4"})
    # union across the 7-day window ending 08-18: u1,u2,u3,u4
    assert wau == 4
    assert mau == 4


@patch("backend.monitoring.product_metrics.db")
def test_classify_funnel(mock_db):
    from backend.monitoring.product_metrics import _classify_funnel
    table = MagicMock()
    # u1: has meta + completed; u2: has meta only; u3: nothing
    mock_db.get_user_meta.side_effect = lambda t, sub: {"x": 1} if sub in ("u1", "u2") else None
    table.get_item.side_effect = lambda Key: {"Item": {"x": 1}} if Key["SK"] == "USER#u1" else {}
    users = [{"sub": "u1"}, {"sub": "u2"}, {"sub": "u3"}]
    funnel = _classify_funnel(table, users)
    assert funnel == {"signed_up": 3, "user_meta": 2, "completed": 1}


@patch("backend.monitoring.product_metrics._list_cognito_users")
@patch("backend.monitoring.product_metrics.db")
@patch("backend.monitoring.product_metrics.boto3")
def test_handler_writes_snapshot(mock_boto3, mock_db, mock_list_users):
    from backend.monitoring.product_metrics import handler
    table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = table

    created = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    mock_list_users.return_value = [
        {"sub": "u1", "created": created, "provider": "federated"},
        {"sub": "u2", "created": datetime(2026, 8, 1, tzinfo=timezone.utc), "provider": "federated"},
    ]
    mock_db.get_user_meta.return_value = {"x": 1}
    table.get_item.return_value = {"Item": {"x": 1}}
    mock_db.list_daily_active_user_ids.return_value = ["u1"]
    mock_db.list_metrics_snapshots.return_value = []
    mock_db.list_workspaces.return_value = []

    result = handler({"day": "2026-08-18"}, None)

    assert result["day"] == "2026-08-18"
    assert result["total_users"] == 2
    assert result["new_signups"] == 1   # only u1 created on 08-18
    assert result["dau"] == 1
    assert "active_user_ids" not in result  # not echoed
    mock_db.put_metrics_snapshot.assert_called_once()
    # snapshot stores the active id list for future WAU/MAU unions
    snap = mock_db.put_metrics_snapshot.call_args[0][2]
    assert snap["active_user_ids"] == ["u1"]

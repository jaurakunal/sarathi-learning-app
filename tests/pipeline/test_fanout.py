"""Unit tests for backend.pipeline.fanout — fan-out Lambda handler.

Tests cover:
- 0 active users triggers 0 executions
- 2 active users starts 2 executions
- Skips inactive users
- Handles SFN errors gracefully (continues with remaining users)
- Missing STATE_MACHINE_ARN returns early
- DDB-based dedup via _can_trigger:
  - Returns True when no record
  - Returns True when status is "succeeded"
  - Returns False when status is "running" and SF confirms RUNNING
  - Returns True when status is "running" but SF says FAILED (stale)
  - Returns True when SF describe throws (assume stale)
  - put_pipeline_run called after successful start_execution
"""

import json
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def env_vars():
    return {
        "TABLE_NAME": "sarathi-test",
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline",
        "BUCKET_NAME": "sarathi-bucket",
    }


@pytest.fixture
def active_users():
    return [
        {"PK": "SYSTEM#USERS", "SK": "USER#user-1", "user_id": "user-1", "status": "active"},
        {"PK": "SYSTEM#USERS", "SK": "USER#user-2", "user_id": "user-2", "status": "active"},
    ]


@pytest.fixture
def mixed_users():
    """Mix of active and inactive users."""
    return [
        {"PK": "SYSTEM#USERS", "SK": "USER#user-1", "user_id": "user-1", "status": "active"},
        {"PK": "SYSTEM#USERS", "SK": "USER#user-2", "user_id": "user-2", "status": "inactive"},
        {"PK": "SYSTEM#USERS", "SK": "USER#user-3", "user_id": "user-3", "status": "active"},
    ]


# ---------------------------------------------------------------------------
# Tests — Handler
# ---------------------------------------------------------------------------


class TestFanoutHandler:
    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.db")
    @patch("backend.pipeline.fanout.boto3")
    def test_zero_active_users_triggers_zero(self, mock_boto3, mock_db):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

        from backend.pipeline.fanout import handler

        result = handler({}, None)

        assert result["users_triggered"] == 0
        mock_sfn.start_execution.assert_not_called()

    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.db")
    @patch("backend.pipeline.fanout.boto3")
    def test_two_active_users_starts_two_executions(self, mock_boto3, mock_db, active_users):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": active_users}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_sfn.start_execution.return_value = {"executionArn": "arn:aws:states:us-east-1:123:execution:abc"}
        mock_boto3.client.return_value = mock_sfn
        # No existing pipeline runs
        mock_db.get_pipeline_run.return_value = None

        def _ws_side(user_id):
            return [{"workspace_id": f"ws-{user_id}", "status": "active", "name": "Default"}]
        mock_db.list_workspaces.side_effect = lambda _table, uid: _ws_side(uid)


        from backend.pipeline.fanout import handler

        result = handler({}, None)

        assert result["users_triggered"] == 2
        assert mock_sfn.start_execution.call_count == 2

        # Verify each call has correct user_id in input
        calls = mock_sfn.start_execution.call_args_list
        inputs = [json.loads(c[1]["input"]) for c in calls]
        user_ids_triggered = {inp["user_id"] for inp in inputs}
        assert user_ids_triggered == {"user-1", "user-2"}

    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.db")
    @patch("backend.pipeline.fanout.boto3")
    def test_skips_inactive_users(self, mock_boto3, mock_db, mixed_users):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": mixed_users}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_sfn.start_execution.return_value = {"executionArn": "arn:aws:states:us-east-1:123:execution:abc"}
        mock_boto3.client.return_value = mock_sfn
        mock_db.get_pipeline_run.return_value = None

        def _ws_side(user_id):
            return [{"workspace_id": f"ws-{user_id}", "status": "active", "name": "Default"}]
        mock_db.list_workspaces.side_effect = lambda _table, uid: _ws_side(uid)


        from backend.pipeline.fanout import handler

        result = handler({}, None)

        # Only user-1 and user-3 are active
        assert result["users_triggered"] == 2
        assert mock_sfn.start_execution.call_count == 2

        calls = mock_sfn.start_execution.call_args_list
        inputs = [json.loads(c[1]["input"]) for c in calls]
        user_ids_triggered = {inp["user_id"] for inp in inputs}
        assert "user-2" not in user_ids_triggered
        assert user_ids_triggered == {"user-1", "user-3"}

    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.db")
    @patch("backend.pipeline.fanout.boto3")
    def test_handles_sfn_errors_gracefully(self, mock_boto3, mock_db, active_users):
        """When SFN fails for one user, it continues with others."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": active_users}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        # First call fails, second succeeds
        mock_sfn.start_execution.side_effect = [
            Exception("Throttled"),
            {"executionArn": "arn:aws:states:us-east-1:123:execution:abc"},
        ]
        mock_boto3.client.return_value = mock_sfn
        mock_db.get_pipeline_run.return_value = None

        def _ws_side(user_id):
            return [{"workspace_id": f"ws-{user_id}", "status": "active", "name": "Default"}]
        mock_db.list_workspaces.side_effect = lambda _table, uid: _ws_side(uid)


        from backend.pipeline.fanout import handler

        result = handler({}, None)

        # Only 1 succeeded
        assert result["users_triggered"] == 1
        assert mock_sfn.start_execution.call_count == 2

    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.boto3")
    def test_returns_zero_when_no_state_machine_arn(self, mock_boto3):
        """When STATE_MACHINE_ARN is empty, returns immediately."""
        from backend.pipeline.fanout import handler

        result = handler({}, None)

        assert result["users_triggered"] == 0
        # Should not even try to query DDB
        mock_boto3.resource.return_value.Table.return_value.query.assert_not_called()

    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.db")
    @patch("backend.pipeline.fanout.boto3")
    def test_passes_correct_input_to_sfn(self, mock_boto3, mock_db, active_users):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": [active_users[0]]}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_sfn.start_execution.return_value = {"executionArn": "arn:exec:123"}
        mock_boto3.client.return_value = mock_sfn
        mock_db.get_pipeline_run.return_value = None

        def _ws_side(user_id):
            return [{"workspace_id": f"ws-{user_id}", "status": "active", "name": "Default"}]
        mock_db.list_workspaces.side_effect = lambda _table, uid: _ws_side(uid)


        from backend.pipeline.fanout import handler

        handler({}, None)

        call_kwargs = mock_sfn.start_execution.call_args[1]
        assert call_kwargs["stateMachineArn"] == "arn:aws:states:us-east-1:123:stateMachine:pipeline"
        sfn_input = json.loads(call_kwargs["input"])
        assert sfn_input["user_id"] == "user-1"
        assert sfn_input["table_name"] == "sarathi-test"
        assert sfn_input["s3_bucket"] == "sarathi-bucket"
        assert sfn_input["since_days"] == 30

    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.db")
    @patch("backend.pipeline.fanout.boto3")
    def test_skips_users_with_empty_user_id(self, mock_boto3, mock_db):
        """Users with missing user_id field are skipped."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": [
            {"PK": "SYSTEM#USERS", "SK": "USER#", "user_id": "", "status": "active"},
            {"PK": "SYSTEM#USERS", "SK": "USER#user-1", "user_id": "user-1", "status": "active"},
        ]}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_sfn.start_execution.return_value = {"executionArn": "arn:exec:123"}
        mock_boto3.client.return_value = mock_sfn
        mock_db.get_pipeline_run.return_value = None

        def _ws_side(user_id):
            return [{"workspace_id": f"ws-{user_id}", "status": "active", "name": "Default"}]
        mock_db.list_workspaces.side_effect = lambda _table, uid: _ws_side(uid)


        from backend.pipeline.fanout import handler

        result = handler({}, None)

        assert result["users_triggered"] == 1
        assert mock_sfn.start_execution.call_count == 1

    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.db")
    @patch("backend.pipeline.fanout.boto3")
    def test_puts_pipeline_run_after_start_execution(self, mock_boto3, mock_db, active_users):
        """After successful start_execution, put_pipeline_run is called."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": [active_users[0]]}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_sfn.start_execution.return_value = {"executionArn": "arn:aws:states:us-east-1:123:execution:new-exec"}
        mock_boto3.client.return_value = mock_sfn
        mock_db.get_pipeline_run.return_value = None

        def _ws_side(user_id):
            return [{"workspace_id": f"ws-{user_id}", "status": "active", "name": "Default"}]
        mock_db.list_workspaces.side_effect = lambda _table, uid: _ws_side(uid)


        from backend.pipeline.fanout import handler

        handler({}, None)

        mock_db.put_pipeline_run.assert_called_once_with(
            mock_table,
            "user-1",
            "ws-user-1",
            "arn:aws:states:us-east-1:123:execution:new-exec",
            "running",
        )


# ---------------------------------------------------------------------------
# Tests — _can_trigger
# ---------------------------------------------------------------------------


class TestCanTrigger:
    @patch("backend.pipeline.fanout.db")
    def test_returns_true_when_no_record(self, mock_db):
        """No pipeline run record means we can trigger."""
        mock_db.get_pipeline_run.return_value = None

        def _ws_side(user_id):
            return [{"workspace_id": f"ws-{user_id}", "status": "active", "name": "Default"}]
        mock_db.list_workspaces.side_effect = lambda _table, uid: _ws_side(uid)

        mock_sfn = MagicMock()
        mock_table = MagicMock()

        from backend.pipeline.fanout import _can_trigger

        result = _can_trigger(mock_table, mock_sfn, "user-1", "ws-1")

        assert result is True
        mock_sfn.describe_execution.assert_not_called()

    @patch("backend.pipeline.fanout.db")
    def test_returns_true_when_status_succeeded(self, mock_db):
        """Record with status=succeeded means we can trigger."""
        mock_db.get_pipeline_run.return_value = {
            "status": "succeeded",
            "execution_arn": "arn:old",
        }
        mock_sfn = MagicMock()
        mock_table = MagicMock()

        from backend.pipeline.fanout import _can_trigger

        result = _can_trigger(mock_table, mock_sfn, "user-1", "ws-1")

        assert result is True
        mock_sfn.describe_execution.assert_not_called()

    @patch("backend.pipeline.fanout.db")
    def test_returns_true_when_status_failed(self, mock_db):
        """Record with status=failed means we can trigger."""
        mock_db.get_pipeline_run.return_value = {
            "status": "failed",
            "execution_arn": "arn:old",
        }
        mock_sfn = MagicMock()
        mock_table = MagicMock()

        from backend.pipeline.fanout import _can_trigger

        result = _can_trigger(mock_table, mock_sfn, "user-1", "ws-1")

        assert result is True
        mock_sfn.describe_execution.assert_not_called()

    @patch("backend.pipeline.fanout.db")
    def test_returns_false_when_genuinely_running(self, mock_db):
        """Record with status=running and SF confirms RUNNING means skip."""
        mock_db.get_pipeline_run.return_value = {
            "status": "running",
            "execution_arn": "arn:aws:states:us-east-1:123:execution:active",
        }
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.return_value = {"status": "RUNNING"}
        mock_table = MagicMock()

        from backend.pipeline.fanout import _can_trigger

        result = _can_trigger(mock_table, mock_sfn, "user-1", "ws-1")

        assert result is False
        mock_sfn.describe_execution.assert_called_once_with(
            executionArn="arn:aws:states:us-east-1:123:execution:active"
        )

    @patch("backend.pipeline.fanout.db")
    def test_returns_true_when_stale_running_sf_says_failed(self, mock_db):
        """Record says running but SF says FAILED — stale, allow trigger."""
        mock_db.get_pipeline_run.return_value = {
            "status": "running",
            "execution_arn": "arn:aws:states:us-east-1:123:execution:stale",
        }
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.return_value = {"status": "FAILED"}
        mock_table = MagicMock()

        from backend.pipeline.fanout import _can_trigger

        result = _can_trigger(mock_table, mock_sfn, "user-1", "ws-1")

        assert result is True
        # Should have updated the stale record
        mock_db.update_pipeline_status.assert_called_once_with(mock_table, "user-1", "ws-1", "failed")

    @patch("backend.pipeline.fanout.db")
    def test_returns_true_when_stale_running_sf_says_succeeded(self, mock_db):
        """Record says running but SF says SUCCEEDED — stale, allow trigger."""
        mock_db.get_pipeline_run.return_value = {
            "status": "running",
            "execution_arn": "arn:aws:states:us-east-1:123:execution:stale",
        }
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.return_value = {"status": "SUCCEEDED"}
        mock_table = MagicMock()

        from backend.pipeline.fanout import _can_trigger

        result = _can_trigger(mock_table, mock_sfn, "user-1", "ws-1")

        assert result is True
        mock_db.update_pipeline_status.assert_called_once_with(mock_table, "user-1", "ws-1", "succeeded")

    @patch("backend.pipeline.fanout.db")
    def test_returns_true_when_stale_running_sf_says_timed_out(self, mock_db):
        """Record says running but SF says TIMED_OUT — maps to failed."""
        mock_db.get_pipeline_run.return_value = {
            "status": "running",
            "execution_arn": "arn:exec:timeout",
        }
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.return_value = {"status": "TIMED_OUT"}
        mock_table = MagicMock()

        from backend.pipeline.fanout import _can_trigger

        result = _can_trigger(mock_table, mock_sfn, "user-1", "ws-1")

        assert result is True
        mock_db.update_pipeline_status.assert_called_once_with(mock_table, "user-1", "ws-1", "failed")

    @patch("backend.pipeline.fanout.db")
    def test_returns_true_when_sf_describe_throws(self, mock_db):
        """If describe_execution fails, assume stale and allow trigger."""
        mock_db.get_pipeline_run.return_value = {
            "status": "running",
            "execution_arn": "arn:exec:broken",
        }
        mock_sfn = MagicMock()
        mock_sfn.describe_execution.side_effect = Exception("AccessDenied")
        mock_table = MagicMock()

        from backend.pipeline.fanout import _can_trigger

        result = _can_trigger(mock_table, mock_sfn, "user-1", "ws-1")

        assert result is True
        # Should not have tried to update — just allow trigger
        mock_db.update_pipeline_status.assert_not_called()

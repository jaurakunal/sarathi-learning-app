"""Unit tests for backend.pipeline.fanout — fan-out Lambda handler.

Tests cover:
- 0 active users triggers 0 executions
- 2 active users starts 2 executions
- Skips inactive users
- Handles SFN errors gracefully (continues with remaining users)
- Missing STATE_MACHINE_ARN returns early
"""

import json
from unittest.mock import MagicMock, patch

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
# Tests
# ---------------------------------------------------------------------------


class TestFanoutHandler:
    @patch.dict("os.environ", {"TABLE_NAME": "sarathi-test", "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline", "BUCKET_NAME": "sarathi-bucket"})
    @patch("backend.pipeline.fanout.boto3")
    def test_zero_active_users_triggers_zero(self, mock_boto3):
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
    @patch("backend.pipeline.fanout.boto3")
    def test_two_active_users_starts_two_executions(self, mock_boto3, active_users):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": active_users}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

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
    @patch("backend.pipeline.fanout.boto3")
    def test_skips_inactive_users(self, mock_boto3, mixed_users):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": mixed_users}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

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
    @patch("backend.pipeline.fanout.boto3")
    def test_handles_sfn_errors_gracefully(self, mock_boto3, active_users):
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
    @patch("backend.pipeline.fanout.boto3")
    def test_passes_correct_input_to_sfn(self, mock_boto3, active_users):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": [active_users[0]]}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

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
    @patch("backend.pipeline.fanout.boto3")
    def test_skips_users_with_empty_user_id(self, mock_boto3):
        """Users with missing user_id field are skipped."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": [
            {"PK": "SYSTEM#USERS", "SK": "USER#", "user_id": "", "status": "active"},
            {"PK": "SYSTEM#USERS", "SK": "USER#user-1", "user_id": "user-1", "status": "active"},
        ]}
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

        from backend.pipeline.fanout import handler

        result = handler({}, None)

        assert result["users_triggered"] == 1
        assert mock_sfn.start_execution.call_count == 1

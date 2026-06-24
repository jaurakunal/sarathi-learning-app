"""Unit tests for backend.api.onboarding_confirm — confirm and save profile.

Tests cover:
- Saves profile meta, areas, hypothesis to DDB
- Registers user in SYSTEM#USERS
- Triggers step function
- Returns 400 if no profile in body
- Returns 401 if unauthorized
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id():
    return "user-confirm-456"


@pytest.fixture
def sample_profile():
    return {
        "meta": {
            "learning_style": {"math": "route-around"},
            "paper_goal": "Clone myself as AI",
            "background": "ML engineer",
        },
        "areas": [
            {"id": "area-1", "label": "Memory Architecture", "status": "active", "role": "spine"},
            {"id": "area-2", "label": "Agentic Harness", "status": "active", "role": "secondary"},
        ],
        "hypothesis": {
            "statement": "Brain-structure + agentic harness >> the LLM.",
            "status": "untested",
        },
    }


@pytest.fixture
def confirm_event(user_id, sample_profile):
    """A POST event with a complete profile body."""
    return {
        "httpMethod": "POST",
        "requestContext": {
            "authorizer": {"claims": {"sub": user_id}},
        },
        "body": json.dumps({"profile": sample_profile}),
    }


@pytest.fixture
def confirm_event_no_profile(user_id):
    """A POST event missing the profile key."""
    return {
        "httpMethod": "POST",
        "requestContext": {
            "authorizer": {"claims": {"sub": user_id}},
        },
        "body": json.dumps({"something_else": "value"}),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOnboardingConfirmHandler:
    @patch("backend.api.onboarding_confirm.boto3")
    @patch("backend.api.onboarding_confirm.db")
    def test_saves_profile_meta(self, mock_db, mock_boto3, confirm_event, user_id):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

        from backend.api.onboarding_confirm import handler

        result = handler(confirm_event, None)

        assert result["statusCode"] == 200
        mock_db.put_profile_meta.assert_called_once()
        call_args = mock_db.put_profile_meta.call_args[0]
        assert call_args[0] == mock_table
        assert call_args[1] == user_id
        meta = call_args[2]
        assert meta["paper_goal"] == "Clone myself as AI"
        assert meta["learning_style"]["math"] == "route-around"

    @patch("backend.api.onboarding_confirm.boto3")
    @patch("backend.api.onboarding_confirm.db")
    def test_saves_areas(self, mock_db, mock_boto3, confirm_event, user_id):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

        from backend.api.onboarding_confirm import handler

        handler(confirm_event, None)

        assert mock_db.put_profile_area.call_count == 2
        first_area = mock_db.put_profile_area.call_args_list[0][0][2]
        assert first_area["id"] == "area-1"
        assert first_area["label"] == "Memory Architecture"

    @patch("backend.api.onboarding_confirm.boto3")
    @patch("backend.api.onboarding_confirm.db")
    def test_saves_hypothesis(self, mock_db, mock_boto3, confirm_event, user_id):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

        from backend.api.onboarding_confirm import handler

        handler(confirm_event, None)

        mock_db.put_profile_hypothesis.assert_called_once()
        hyp = mock_db.put_profile_hypothesis.call_args[0][2]
        assert hyp["statement"] == "Brain-structure + agentic harness >> the LLM."

    @patch("backend.api.onboarding_confirm.boto3")
    @patch("backend.api.onboarding_confirm.db")
    def test_registers_user_in_system_users(self, mock_db, mock_boto3, confirm_event, user_id):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

        from backend.api.onboarding_confirm import handler

        handler(confirm_event, None)

        # Find the put_item call for SYSTEM#USERS registration
        put_calls = mock_table.put_item.call_args_list
        assert len(put_calls) >= 1
        user_reg_item = put_calls[0][1]["Item"]
        assert user_reg_item["PK"] == "SYSTEM#USERS"
        assert user_reg_item["SK"] == f"USER#{user_id}"
        assert user_reg_item["user_id"] == user_id
        assert user_reg_item["status"] == "active"
        assert "registered_at" in user_reg_item

    @patch("backend.api.onboarding_confirm.os")
    @patch("backend.api.onboarding_confirm.boto3")
    @patch("backend.api.onboarding_confirm.db")
    def test_triggers_step_function(self, mock_db, mock_boto3, mock_os, confirm_event, user_id):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn
        mock_os.environ.get.side_effect = lambda key, default="": {
            "TABLE_NAME": "sarathi",
            "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:pipeline",
            "BUCKET_NAME": "sarathi-bucket",
        }.get(key, default)

        from backend.api.onboarding_confirm import handler

        handler(confirm_event, None)

        mock_sfn.start_execution.assert_called_once()
        call_kwargs = mock_sfn.start_execution.call_args[1]
        assert "stateMachineArn" in call_kwargs
        sfn_input = json.loads(call_kwargs["input"])
        assert sfn_input["user_id"] == user_id

    @patch("backend.api.onboarding_confirm.boto3")
    @patch("backend.api.onboarding_confirm.db")
    def test_returns_400_when_no_profile(self, mock_db, mock_boto3, confirm_event_no_profile):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        from backend.api.onboarding_confirm import handler

        result = handler(confirm_event_no_profile, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "profile required" in body["error"]

    def test_returns_401_when_unauthorized(self):
        event = {
            "httpMethod": "POST",
            "requestContext": {"authorizer": {"claims": {}}},
            "body": json.dumps({"profile": {}}),
        }

        from backend.api.onboarding_confirm import handler

        result = handler(event, None)

        assert result["statusCode"] == 401

    @patch("backend.api.onboarding_confirm.boto3")
    @patch("backend.api.onboarding_confirm.db")
    def test_succeeds_even_if_sfn_trigger_fails(self, mock_db, mock_boto3, confirm_event, user_id):
        """Handler should succeed even if step function trigger fails (user waits for nightly)."""
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_sfn.start_execution.side_effect = Exception("SFN unavailable")
        mock_boto3.client.return_value = mock_sfn

        from backend.api.onboarding_confirm import handler

        result = handler(confirm_event, None)

        # Should still succeed — SFN failure is non-fatal
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "confirmed"

    @patch("backend.api.onboarding_confirm.boto3")
    @patch("backend.api.onboarding_confirm.db")
    def test_skips_hypothesis_when_no_statement(self, mock_db, mock_boto3, user_id):
        """Should not save hypothesis if statement is empty."""
        profile = {
            "meta": {"paper_goal": "Learn"},
            "areas": [],
            "hypothesis": {"statement": "", "status": "untested"},
        }
        event = {
            "httpMethod": "POST",
            "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
            "body": json.dumps({"profile": profile}),
        }
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_sfn = MagicMock()
        mock_boto3.client.return_value = mock_sfn

        from backend.api.onboarding_confirm import handler

        handler(event, None)

        mock_db.put_profile_hypothesis.assert_not_called()

"""Unit tests for backend.api.onboarding — onboarding chat handler.

Tests cover:
- GET returns has_profile: false/true based on profile existence
- POST with message returns LLM response
- _extract_profile() parses JSON from markdown fences correctly
- _extract_profile() returns None when no profile JSON
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id():
    return "user-onboard-123"


@pytest.fixture
def get_event(user_id):
    """A minimal API Gateway GET event with Cognito authorizer claims."""
    return {
        "httpMethod": "GET",
        "requestContext": {
            "authorizer": {"claims": {"sub": user_id}},
        },
        "body": None,
    }


@pytest.fixture
def post_event(user_id):
    """A minimal API Gateway POST event with a message body."""
    return {
        "httpMethod": "POST",
        "requestContext": {
            "authorizer": {"claims": {"sub": user_id}},
        },
        "body": json.dumps({"message": "I work on AI agents"}),
    }


@pytest.fixture
def post_event_empty_message(user_id):
    """POST event with empty message (first contact)."""
    return {
        "httpMethod": "POST",
        "requestContext": {
            "authorizer": {"claims": {"sub": user_id}},
        },
        "body": json.dumps({"message": ""}),
    }


# ---------------------------------------------------------------------------
# GET /onboarding tests
# ---------------------------------------------------------------------------


class TestOnboardingGet:
    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_returns_has_profile_false_when_no_profile(self, mock_db, mock_boto3, get_event):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_full_profile.return_value = {"meta": None, "areas": [], "hypothesis": None, "summaries": []}

        from backend.api.onboarding import handler

        result = handler(get_event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["has_profile"] is False

    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_returns_has_profile_true_when_profile_exists(self, mock_db, mock_boto3, get_event):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_full_profile.return_value = {
            "meta": {"paper_goal": "Clone myself"},
            "areas": [{"id": "a1"}],
            "hypothesis": None,
            "summaries": [],
        }

        from backend.api.onboarding import handler

        result = handler(get_event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["has_profile"] is True


# ---------------------------------------------------------------------------
# POST /onboarding tests
# ---------------------------------------------------------------------------


class TestOnboardingPost:
    @patch("backend.api.onboarding.call_llm_multi")
    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_post_returns_llm_response(self, mock_db, mock_boto3, mock_call_llm, post_event):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = {"conv_id": "onboarding"}
        mock_db.get_conversation_turns.return_value = []
        mock_call_llm.return_value = "What kind of AI agents do you build?"

        from backend.api.onboarding import handler

        result = handler(post_event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["response"] == "What kind of AI agents do you build?"
        assert body["turn_seq"] == 1

    @patch("backend.api.onboarding.call_llm_multi")
    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_post_returns_500_when_llm_fails(self, mock_db, mock_boto3, mock_call_llm, post_event):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = {"conv_id": "onboarding"}
        mock_db.get_conversation_turns.return_value = []
        mock_call_llm.return_value = None

        from backend.api.onboarding import handler

        result = handler(post_event, None)

        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert "error" in body

    @patch("backend.api.onboarding.call_llm_multi")
    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_post_creates_conversation_if_none_exists(self, mock_db, mock_boto3, mock_call_llm, post_event):
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_conversation_by_paper.return_value = None
        mock_db.get_conversation_turns.return_value = []
        mock_call_llm.return_value = "Hello!"

        from backend.api.onboarding import handler

        handler(post_event, None)

        mock_db.create_conversation.assert_called_once_with(mock_table, "user-onboard-123", "ws-test-fixture", "onboarding", "")

    def test_unauthorized_returns_401(self):
        event = {
            "httpMethod": "GET",
            "requestContext": {"authorizer": {"claims": {}}},
            "body": None,
        }

        from backend.api.onboarding import handler

        result = handler(event, None)

        assert result["statusCode"] == 401

    def test_unsupported_method_returns_405(self):
        event = {
            "httpMethod": "DELETE",
            "requestContext": {"authorizer": {"claims": {"sub": "user-1"}}},
            "body": None,
        }

        from backend.api.onboarding import handler

        result = handler(event, None)

        assert result["statusCode"] == 405


# ---------------------------------------------------------------------------
# _extract_profile() tests
# ---------------------------------------------------------------------------


class TestExtractProfile:
    def test_extracts_profile_from_json_fences(self):
        from backend.api.onboarding import _extract_profile

        response = '''Based on our conversation, here's your profile:

```json
{
  "type": "profile_complete",
  "confidence": 0.92,
  "summary": "You are an AI researcher focused on agents.",
  "profile": {
    "areas": [{"id": "a1", "label": "Agents"}],
    "meta": {"paper_goal": "Build agents"},
    "hypothesis": {"statement": "Agents need memory"}
  }
}
```

Does this look right?'''

        result = _extract_profile(response)

        assert result is not None
        assert result["type"] == "profile_complete"
        assert result["confidence"] == 0.92
        assert result["profile"]["areas"][0]["label"] == "Agents"

    def test_returns_none_when_no_profile_complete_keyword(self):
        from backend.api.onboarding import _extract_profile

        response = "Tell me more about your research interests."

        result = _extract_profile(response)

        assert result is None

    def test_returns_none_when_no_json_fences(self):
        from backend.api.onboarding import _extract_profile

        response = "profile_complete but no JSON fences around it"

        result = _extract_profile(response)

        assert result is None

    def test_returns_none_when_json_is_invalid(self):
        from backend.api.onboarding import _extract_profile

        response = '''Here's the profile_complete:

```json
{this is not valid json}
```
'''

        result = _extract_profile(response)

        assert result is None

    def test_returns_none_when_type_is_not_profile_complete(self):
        from backend.api.onboarding import _extract_profile

        response = '''profile_complete mentioned above.

```json
{
  "type": "something_else",
  "profile": {"areas": []}
}
```
'''

        result = _extract_profile(response)

        assert result is None

    def test_returns_none_when_no_profile_key_in_json(self):
        from backend.api.onboarding import _extract_profile

        response = '''profile_complete:

```json
{
  "type": "profile_complete",
  "confidence": 0.95,
  "summary": "Summary without profile key"
}
```
'''

        result = _extract_profile(response)

        assert result is None

    def test_extracts_from_plain_backtick_fences(self):
        from backend.api.onboarding import _extract_profile

        response = '''profile_complete

```
{
  "type": "profile_complete",
  "confidence": 0.91,
  "summary": "A researcher.",
  "profile": {
    "areas": [],
    "meta": {},
    "hypothesis": {}
  }
}
```
'''

        result = _extract_profile(response)

        assert result is not None
        assert result["type"] == "profile_complete"

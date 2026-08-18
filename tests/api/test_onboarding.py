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

    @patch("backend.api.onboarding.call_llm_multi")
    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_workspace_stage_hydration_returns_last_assistant_response(
        self, mock_db, mock_boto3, mock_call_llm, user_id,
    ):
        """Empty message + existing turns must NOT call the LLM (would crash Bedrock).

        Instead the handler returns the last assistant response so the frontend
        can rehydrate the chat.
        """
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_user_meta.return_value = {"background": "SDE"}  # → workspace stage
        mock_db.get_conversation_by_paper.return_value = {"conv_id": "onboarding"}
        mock_db.get_conversation_turns.return_value = [
            {"seq": 1, "request": "hi", "response": "What's your goal?"},
        ]

        event = {
            "httpMethod": "POST",
            "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
            "body": json.dumps({"message": "", "stage": "workspace"}),
        }
        from backend.api.onboarding import handler

        result = handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["stage"] == "workspace"
        assert body["response"] == "What's your goal?"
        assert body["turn_seq"] == 1
        mock_call_llm.assert_not_called()

    @patch("backend.api.onboarding.call_llm_multi")
    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_user_stage_hydration_returns_last_assistant_response(
        self, mock_db, mock_boto3, mock_call_llm, user_id,
    ):
        """Same hydration behavior for user stage."""
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_db.get_user_meta.return_value = None  # → user stage
        mock_db.get_user_onboarding_status.return_value = None

        # Simulate the pre-workspace user-stage turns partition.
        mock_table.query.return_value = {
            "Items": [
                {"seq": 1, "request": "hi", "response": "Tell me about your background."},
            ]
        }

        event = {
            "httpMethod": "POST",
            "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
            "body": json.dumps({"message": "", "stage": "user"}),
        }
        from backend.api.onboarding import handler

        result = handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["stage"] == "user"
        assert body["response"] == "Tell me about your background."
        assert body["turn_seq"] == 1
        mock_call_llm.assert_not_called()

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

    def test_boolean_flag_with_nested_user_payload(self):
        """Regression: kunaljaura@gmail.com 2026-08-18. Model emitted a boolean
        profile_complete flag with the payload nested under 'user', focus_areas
        instead of areas, and a string hypothesis. Previously returned None ->
        raw JSON + Skip button, nothing saved."""
        from backend.api.onboarding import _extract_profile

        response = '''Great, I have a clear picture.

```json
{
  "profile_complete": true,
  "user": {
    "role": "engineer_transitioning_to_researcher",
    "domain": "backend_software_and_ai_agents",
    "focus_areas": ["long_running_agent_reliability", "agentic_evaluation"],
    "hypothesis": "persistent_memory_plus_disciplined_harness_improves_faithfulness",
    "summary": "An engineer moving into agent-reliability research."
  }
}
```
'''
        result = _extract_profile(response)
        assert result is not None
        assert result["type"] == "profile_complete"
        labels = [a["label"] for a in result["profile"]["areas"]]
        assert any("long_running_agent_reliability" in l for l in labels)
        assert result["profile"]["hypothesis"]["statement"].startswith("persistent_memory")

    def test_boolean_flag_with_profile_wrapper(self):
        from backend.api.onboarding import _extract_profile

        response = '''```json
{
  "profile_complete": true,
  "summary": "top-level summary",
  "profile": {
    "areas": [{"id": "a1", "label": "Evals"}],
    "hypothesis": {"statement": "x"}
  }
}
```'''
        result = _extract_profile(response)
        assert result is not None
        assert result["profile"]["areas"][0]["label"] == "Evals"
        assert result["summary"] == "top-level summary"

    def test_user_meta_boolean_flag_with_flat_fields(self):
        from backend.api.onboarding import _extract_user_meta

        response = '''```json
{
  "user_meta_complete": true,
  "background": "SDE",
  "learning_style": "reads-to-build",
  "math_comfort": "low"
}
```'''
        result = _extract_user_meta(response)
        assert result is not None
        assert result["type"] == "user_meta_complete"
        assert result["user_meta"]["background"] == "SDE"

    def test_explicit_wrong_type_still_rejected(self):
        """Guard: an explicit non-completion type must NOT be coerced."""
        from backend.api.onboarding import _extract_profile

        response = '''```json
{"type": "clarifying_question", "profile": {"areas": []}}
```'''
        assert _extract_profile(response) is None

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


# ---------------------------------------------------------------------------
# Onboarding hardening: readiness gate, model fallback, dropdown catalog
# ---------------------------------------------------------------------------


class TestReadinessAndFallback:
    @patch("backend.api.onboarding.call_llm")
    def test_assess_readiness_ready_with_profile(self, mock_call_llm):
        from backend.api.onboarding import _assess_readiness
        mock_call_llm.return_value = '''```json
{"ready": true, "confidence": 0.9, "missing": [],
 "profile": {"areas": [{"id": "rag", "label": "RAG", "role": "primary"}],
             "meta": {"paper_goal": "learn RAG"}}}
```'''
        r = _assess_readiness([{"role": "user", "content": "I care about RAG"}])
        assert r["ready"] is True
        assert r["confidence"] == 0.9
        assert r["profile"]["areas"][0]["id"] == "rag"

    @patch("backend.api.onboarding.call_llm")
    def test_assess_readiness_not_ready(self, mock_call_llm):
        from backend.api.onboarding import _assess_readiness
        mock_call_llm.return_value = '{"ready": false, "confidence": 0.2, "missing": ["areas"]}'
        r = _assess_readiness([{"role": "user", "content": "hi"}])
        assert r["ready"] is False

    @patch("backend.api.onboarding.call_llm")
    def test_assess_readiness_failsafe_on_none(self, mock_call_llm):
        from backend.api.onboarding import _assess_readiness
        mock_call_llm.return_value = None
        r = _assess_readiness([{"role": "user", "content": "hi"}])
        assert r["ready"] is False
        assert r["confidence"] == 0.0

    @patch("backend.api.onboarding.call_llm_multi")
    def test_generate_turn_falls_back_on_primary_failure(self, mock_multi):
        from backend.api.onboarding import _generate_turn, ONBOARDING_MODEL, ONBOARDING_FALLBACK_MODEL
        # Primary returns None, fallback returns text.
        mock_multi.side_effect = [None, "fallback response"]
        out = _generate_turn("sys", [{"role": "user", "content": "hi"}], max_tokens=100)
        assert out == "fallback response"
        assert mock_multi.call_count == 2
        # Second call used the fallback model.
        assert mock_multi.call_args_list[1].kwargs["model_id"] == ONBOARDING_FALLBACK_MODEL

    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_get_status_includes_areas_catalog(self, mock_db, mock_boto3):
        from backend.api.onboarding import handler, AREAS_CATALOG
        mock_boto3.resource.return_value.Table.return_value = MagicMock()
        mock_db.get_user_meta.return_value = None
        mock_db.get_user_onboarding_status.return_value = None
        event = {
            "httpMethod": "GET",
            "requestContext": {"authorizer": {"claims": {"sub": "u1"}}},
            "body": None,
        }
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["areas_catalog"] == AREAS_CATALOG
        assert len(body["areas_catalog"]) >= 5

    @patch("backend.api.onboarding._assess_readiness")
    @patch("backend.api.onboarding._generate_turn")
    @patch("backend.api.onboarding.resolve_workspace_id", return_value="w1")
    @patch("backend.api.onboarding.boto3")
    @patch("backend.api.onboarding.db")
    def test_workspace_stage_completes_via_readiness_gate(
        self, mock_db, mock_boto3, mock_resolve, mock_gen, mock_ready,
    ):
        """When the interview model does NOT emit an inline completion block,
        the separate readiness check unlocks completion."""
        mock_boto3.resource.return_value.Table.return_value = MagicMock()
        mock_db.get_user_meta.return_value = {"background": "SDE"}
        mock_db.get_conversation_by_paper.return_value = {"conv_id": "onboarding"}
        mock_db.get_conversation_turns.return_value = []
        # A plain conversational turn, no JSON block.
        mock_gen.return_value = "Got it — sounds like RAG is your focus."
        mock_ready.return_value = {
            "ready": True, "confidence": 0.85, "missing": [],
            "profile": {"areas": [{"id": "rag", "label": "RAG", "role": "primary"}],
                        "meta": {"paper_goal": "learn RAG"}},
        }
        from backend.api.onboarding import handler
        event = {
            "httpMethod": "POST",
            "requestContext": {"authorizer": {"claims": {"sub": "u1"}}},
            "body": json.dumps({"message": "I care about RAG", "stage": "workspace"}),
        }
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["profile_complete"] is True
        assert body["profile"]["areas"][0]["id"] == "rag"

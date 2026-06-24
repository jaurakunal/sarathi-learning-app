"""Integration tests for Sarathi API flows.

These tests hit the REAL deployed APIs using a real Cognito token for the TEST user.
They require:
  - SARATHI_TEST_PASSWORD env var set
  - AWS credentials with DDB access (for setup/teardown)
  - The API to be deployed and accessible

Run with:
    SARATHI_TEST_PASSWORD=xxx pytest tests/integration/ -m integration -v
"""

import uuid

import pytest
import requests

pytestmark = pytest.mark.integration


# ===========================================================================
# Feed Tests
# ===========================================================================


class TestFeed:
    """Tests for GET /feed and GET /feed/{card_id}."""

    def test_feed_returns_cards(self, api, setup_test_data):
        """GET /feed returns 200 with a non-empty cards list."""
        r = api.get("/feed")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert "cards" in body
        assert len(body["cards"]) > 0, "Expected cards (test user has cloned data)"

    def test_feed_card_has_expected_fields(self, api, setup_test_data):
        """Feed cards include engagement state fields."""
        r = api.get("/feed")
        assert r.status_code == 200
        card = r.json()["cards"][0]
        # Check standard card fields
        assert "card_id" in card
        assert "paper_id" in card
        # Check engagement state fields
        for field in ("read", "bookmarked", "rating", "view_count"):
            assert field in card, f"Missing field: {field}"

    def test_feed_card_detail(self, api, setup_test_data):
        """GET /feed/{card_id} returns full card detail."""
        # Get a card_id from the feed
        r = api.get("/feed")
        assert r.status_code == 200
        cards = r.json()["cards"]
        assert len(cards) > 0
        card_id = cards[0]["card_id"]

        # Fetch detail
        r2 = api.get(f"/feed/{card_id}")
        assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text[:200]}"
        body = r2.json()
        assert "hook" in body
        assert "digest" in body
        assert "paper_id" in body


# ===========================================================================
# Engagement Tests
# ===========================================================================


class TestEngagement:
    """Tests for POST /engagement."""

    def test_engagement_view(self, api, setup_test_data):
        """POST /engagement with view action returns 201."""
        # Get a card to engage with
        r = api.get("/feed")
        card = r.json()["cards"][0]

        r2 = api.post("/engagement", json={
            "paper_id": card["paper_id"],
            "card_id": card["card_id"],
            "action": "view",
        })
        assert r2.status_code == 201, f"Expected 201, got {r2.status_code}: {r2.text[:200]}"


# ===========================================================================
# Profile Tests
# ===========================================================================


class TestProfile:
    """Tests for GET /profile."""

    def test_profile_returns_200(self, api, setup_test_data):
        """GET /profile returns 200 with profile data."""
        r = api.get("/profile")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"


# ===========================================================================
# Library Tests
# ===========================================================================


class TestLibrary:
    """Tests for GET /library."""

    def test_library_returns_200(self, api, setup_test_data):
        """GET /library returns 200."""
        r = api.get("/library")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"


# ===========================================================================
# Research Tests
# ===========================================================================


class TestResearch:
    """Tests for GET /research."""

    def test_research_returns_stats(self, api, setup_test_data):
        """GET /research returns 200 with stats."""
        r = api.get("/research")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"


# ===========================================================================
# Settings Tests
# ===========================================================================


class TestSettings:
    """Tests for GET /settings and PUT /settings."""

    def test_settings_get(self, api, setup_test_data):
        """GET /settings returns 200."""
        r = api.get("/settings")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"

    def test_settings_pause_and_resume(self, api, setup_test_data):
        """PUT /settings can pause and resume the pipeline."""
        # Pause
        r = api.put("/settings", json={"pipeline_status": "paused"})
        assert r.status_code == 200, f"Pause failed: {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("pipeline_status") == "paused"

        # Resume
        r2 = api.put("/settings", json={"pipeline_status": "active"})
        assert r2.status_code == 200, f"Resume failed: {r2.status_code}: {r2.text[:200]}"
        body2 = r2.json()
        assert body2.get("pipeline_status") == "active"


# ===========================================================================
# Conversations Tests
# ===========================================================================


class TestConversations:
    """Tests for conversations CRUD: POST, GET, PUT, DELETE."""

    def test_conversation_lifecycle(self, api, setup_test_data):
        """Full lifecycle: create, list (includes it), update title, delete, list (excludes it)."""
        # CREATE
        r = api.post("/conversations", json={
            "title": "Integration Test Conversation",
            "paper_id": setup_test_data["paper_ids"][0] if setup_test_data["paper_ids"] else "test-paper-123",
        })
        assert r.status_code in (200, 201), f"Create failed: {r.status_code}: {r.text[:200]}"
        created = r.json()
        conv_id = created.get("conv_id") or created.get("conversation_id") or created.get("id")
        assert conv_id, f"No conv_id in response: {created}"

        # LIST — should include the new conversation
        r2 = api.get("/conversations")
        assert r2.status_code == 200
        conversations = r2.json().get("conversations", r2.json().get("items", []))
        conv_ids = [c.get("conv_id") or c.get("conversation_id") or c.get("id") for c in conversations]
        assert conv_id in conv_ids, f"Created conversation {conv_id} not found in list"

        # UPDATE title
        new_title = "Updated Integration Test Title"
        r3 = api.put(f"/conversations/{conv_id}", json={"title": new_title})
        assert r3.status_code == 200, f"Update failed: {r3.status_code}: {r3.text[:200]}"

        # DELETE
        r4 = api.delete(f"/conversations/{conv_id}")
        assert r4.status_code == 200, f"Delete failed: {r4.status_code}: {r4.text[:200]}"

        # LIST — should no longer include the deleted conversation
        r5 = api.get("/conversations")
        assert r5.status_code == 200
        conversations_after = r5.json().get("conversations", r5.json().get("items", []))
        conv_ids_after = [c.get("conv_id") or c.get("conversation_id") or c.get("id") for c in conversations_after]
        assert conv_id not in conv_ids_after, "Deleted conversation still appears in list"


# ===========================================================================
# Onboarding Tests
# ===========================================================================


class TestOnboarding:
    """Tests for GET /onboarding."""

    def test_onboarding_has_profile(self, api, setup_test_data):
        """GET /onboarding returns has_profile true (since we cloned profile data)."""
        r = api.get("/onboarding")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("has_profile") is True, f"Expected has_profile=True, got: {body}"


# ===========================================================================
# Suggestions Tests
# ===========================================================================


class TestSuggestions:
    """Tests for POST /suggestions."""

    def test_suggestions_with_paper_id(self, api, setup_test_data):
        """POST /suggestions with a valid paper_id returns 200."""
        paper_ids = setup_test_data.get("paper_ids", [])
        if not paper_ids:
            pytest.skip("No paper_ids available from cloned data")

        r = api.post("/suggestions", json={"paper_id": paper_ids[0]})
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"


# ===========================================================================
# Chat Tests
# ===========================================================================


class TestChat:
    """Tests for GET /chat/{paper_id}."""

    def test_chat_history(self, api, setup_test_data):
        """GET /chat/{paper_id} returns 200 with turns array."""
        paper_ids = setup_test_data.get("paper_ids", [])
        if not paper_ids:
            pytest.skip("No paper_ids available from cloned data")

        r = api.get(f"/chat/{paper_ids[0]}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert "turns" in body, f"Expected 'turns' key in response, got: {list(body.keys())}"


# ===========================================================================
# Push Subscription Tests
# ===========================================================================


class TestPush:
    """Tests for POST /push/subscriptions and DELETE /push/subscriptions."""

    def test_push_subscribe_and_unsubscribe(self, api, setup_test_data):
        """POST then DELETE push subscription works."""
        fake_endpoint = f"https://fcm.googleapis.com/fcm/send/test-{uuid.uuid4().hex[:8]}"
        fake_subscription = {
            "endpoint": fake_endpoint,
            "keys": {
                "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8p8REfWI8",
                "auth": "tBHItJI5svbpC7DP0RM3SA",
            },
        }

        # Subscribe
        r = api.post("/push/subscriptions", json={"subscription": fake_subscription})
        assert r.status_code == 200, f"Subscribe failed: {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("status") == "subscribed"

        # Unsubscribe
        r2 = api.delete("/push/subscriptions", json={"endpoint": fake_endpoint})
        assert r2.status_code == 200, f"Unsubscribe failed: {r2.status_code}: {r2.text[:200]}"
        body2 = r2.json()
        assert body2.get("status") == "unsubscribed"

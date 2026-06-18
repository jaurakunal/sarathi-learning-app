"""API integration test — validates all endpoints work end-to-end.

Hits the real deployed API with a real Cognito token.
Tests: CORS, auth, feed listing, single card, engagement posting, chat.

Usage:
    AWS_PROFILE=poc python scripts/api_integration_test.py

Requires: a valid Cognito session (run once interactively to cache tokens).
"""

import json
import os
import sys
import time

import boto3
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_URL = "https://abcde12345.execute-api.us-east-1.amazonaws.com/prod"
COGNITO_USER_POOL_ID = "us-east-1_XXXXXXXXX"
COGNITO_CLIENT_ID = "your-cognito-app-client-id"
ORIGIN = "https://d0000000000000.cloudfront.net"
USER_EMAIL = os.environ.get("TEST_USER_EMAIL", "")
USER_PASSWORD = os.environ.get("TEST_USER_PASSWORD", "")

passed = 0
failed = 0
errors = []


def test(name):
    """Decorator for test functions."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            global passed, failed
            try:
                fn(*args, **kwargs)
                passed += 1
                print(f"  ✓ {name}")
            except AssertionError as e:
                failed += 1
                errors.append(f"{name}: {e}")
                print(f"  ✗ {name}: {e}")
            except Exception as e:
                failed += 1
                errors.append(f"{name}: {type(e).__name__}: {e}")
                print(f"  ✗ {name}: {type(e).__name__}: {e}")
        wrapper.__name__ = name
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def get_token():
    """Get a valid Cognito ID token via SRP auth."""
    if not USER_EMAIL or not USER_PASSWORD:
        print("ERROR: Set TEST_USER_EMAIL and TEST_USER_PASSWORD env vars")
        sys.exit(1)

    client = boto3.client("cognito-idp", region_name="us-east-1")
    resp = client.initiate_auth(
        ClientId=COGNITO_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": USER_EMAIL,
            "PASSWORD": USER_PASSWORD,
        },
    )
    return resp["AuthenticationResult"]["IdToken"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@test("GET /feed returns 200 with cards array")
def test_feed_list(token):
    r = requests.get(
        f"{API_URL}/feed",
        headers={"Authorization": token, "Origin": ORIGIN},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert "cards" in body, f"Missing 'cards' key in response"
    assert isinstance(body["cards"], list)


@test("GET /feed has CORS header")
def test_feed_cors(token):
    r = requests.get(
        f"{API_URL}/feed",
        headers={"Authorization": token, "Origin": ORIGIN},
    )
    assert "access-control-allow-origin" in r.headers, f"No CORS header. Headers: {dict(r.headers)}"


@test("GET /feed without auth returns 401")
def test_feed_no_auth():
    r = requests.get(f"{API_URL}/feed")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


@test("GET /feed/{card_id} returns card detail")
def test_feed_card_detail(token, card_id):
    r = requests.get(
        f"{API_URL}/feed/{card_id}",
        headers={"Authorization": token},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert "hook" in body
    assert "digest" in body


@test("POST /engagement returns 201")
def test_engagement_post(token, card):
    r = requests.post(
        f"{API_URL}/engagement",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={
            "paper_id": card["paper_id"],
            "card_id": card["card_id"],
            "action": "view",
        },
    )
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["status"] == "ok"


@test("POST /engagement has CORS header")
def test_engagement_cors(token, card):
    r = requests.post(
        f"{API_URL}/engagement",
        headers={"Authorization": token, "Content-Type": "application/json", "Origin": ORIGIN},
        json={"paper_id": card["paper_id"], "card_id": card["card_id"], "action": "view"},
    )
    assert "access-control-allow-origin" in r.headers


@test("POST /engagement with invalid action returns 400")
def test_engagement_invalid_action(token):
    r = requests.post(
        f"{API_URL}/engagement",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"paper_id": "x", "action": "invalid"},
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"


@test("POST /chat returns 200 with response")
def test_chat(token, card):
    r = requests.post(
        f"{API_URL}/chat",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"paper_id": card["paper_id"], "message": "What is this paper about in one sentence?"},
        timeout=30,
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert "response" in body, f"Missing 'response' in: {body}"
    assert len(body["response"]) > 10, f"Response too short: {body['response']}"


@test("POST /chat has CORS header")
def test_chat_cors(token, card):
    r = requests.post(
        f"{API_URL}/chat",
        headers={"Authorization": token, "Content-Type": "application/json", "Origin": ORIGIN},
        json={"paper_id": card["paper_id"], "message": "test"},
        timeout=30,
    )
    assert "access-control-allow-origin" in r.headers, f"No CORS header on chat response. Headers: {dict(r.headers)}"


@test("POST /chat without auth returns 401 with CORS")
def test_chat_no_auth():
    r = requests.post(
        f"{API_URL}/chat",
        headers={"Content-Type": "application/json", "Origin": ORIGIN},
        json={"paper_id": "x", "message": "test"},
    )
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    assert "access-control-allow-origin" in r.headers, f"No CORS on 401. Headers: {dict(r.headers)}"


@test("OPTIONS preflight on /chat returns CORS headers")
def test_chat_preflight():
    r = requests.options(
        f"{API_URL}/chat",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert r.status_code in (200, 204), f"Expected 200/204, got {r.status_code}"
    assert "access-control-allow-origin" in r.headers


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("\n=== API Integration Test ===\n")
    print(f"API: {API_URL}")
    print(f"Origin: {ORIGIN}")
    print()

    # Auth
    print("[Auth]")
    token = get_token()
    print(f"  ✓ Got Cognito token (first 20 chars: {token[:20]}...)")
    print()

    # Feed tests
    print("[Feed]")
    test_feed_list(token)
    test_feed_cors(token)
    test_feed_no_auth()

    # Get a real card for subsequent tests
    r = requests.get(f"{API_URL}/feed?limit=1", headers={"Authorization": token})
    cards = r.json().get("cards", [])
    if cards:
        card = cards[0]
        test_feed_card_detail(token, card["card_id"])
    else:
        print("  ⚠ No cards in feed — skipping card detail + engagement + chat tests")
        card = None
    print()

    # Engagement tests
    print("[Engagement]")
    if card:
        test_engagement_post(token, card)
        test_engagement_cors(token, card)
    test_engagement_invalid_action(token)
    print()

    # Chat tests
    print("[Chat]")
    test_chat_preflight()
    test_chat_no_auth()
    if card:
        test_chat(token, card)
        test_chat_cors(token, card)
    print()

    # Summary
    total = passed + failed
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  • {e}")
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

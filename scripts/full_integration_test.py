"""Full integration test: API + Pipeline + Learn step.

Tests the entire Sarathi flow against real AWS using the test user
(447844a8-c0e1-700b-2fdf-f9512eee3e49 / kunal@example.com).

Usage:
    AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python scripts/full_integration_test.py

Requires: TEST_USER_EMAIL and TEST_USER_PASSWORD env vars
          (or defaults to kunal@example.com / SarathiTest1!)
"""

import json
import os
import sys
import time

import boto3
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SOURCE_USER_ID = "00000000-0000-0000-0000-000000000000"  # Real user (data source, never modified)
TEST_USER_ID = "447844a8-c0e1-700b-2fdf-f9512eee3e49"   # Test user (cloned into, cleaned after)
TEST_USER_EMAIL = os.environ.get("TEST_USER_EMAIL", "kunal@example.com")
TEST_USER_PASSWORD = os.environ.get("TEST_USER_PASSWORD", "SarathiTest1!")
TABLE_NAME = "sarathi"
S3_BUCKET = "sarathi-123456789012-us-east-1"
API_URL = "https://abcde12345.execute-api.us-east-1.amazonaws.com/prod"
COGNITO_CLIENT_ID = "your-cognito-app-client-id"
ORIGIN = "https://d0000000000000.cloudfront.net"

passed = 0
failed = 0
errors = []


# ---------------------------------------------------------------------------
# Test Data Management
# ---------------------------------------------------------------------------

def cleanup_test_data():
    """Delete ALL data for the test user from DDB. Idempotent."""
    from boto3.dynamodb.conditions import Attr

    session = boto3.Session(region_name="us-east-1")
    dynamodb = session.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    prefix = f"USER#{TEST_USER_ID}"
    items = []
    response = table.scan(FilterExpression=Attr("PK").begins_with(prefix))
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.scan(
            FilterExpression=Attr("PK").begins_with(prefix),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    if items:
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    print(f"  Cleanup: deleted {len(items)} items for test user")


def create_test_data():
    """Clone ALL data from the real user to the test user.

    Keeps S3 keys pointing at the real user's files (same account, Lambda
    role can read both). Only DDB data is cloned.
    """
    from boto3.dynamodb.conditions import Attr

    session = boto3.Session(region_name="us-east-1")
    dynamodb = session.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    prefix = f"USER#{SOURCE_USER_ID}"
    items = []
    response = table.scan(FilterExpression=Attr("PK").begins_with(prefix))
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.scan(
            FilterExpression=Attr("PK").begins_with(prefix),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    with table.batch_writer() as batch:
        for item in items:
            new_item = dict(item)
            # Replace user ID in PK
            new_item["PK"] = item["PK"].replace(SOURCE_USER_ID, TEST_USER_ID)
            # Replace in user_id field
            if "user_id" in new_item:
                new_item["user_id"] = TEST_USER_ID
            # Fix GSI keys that contain user_id
            for key in ("gsi1pk", "gsi2pk", "gsi3pk", "gsi4pk"):
                if key in new_item and SOURCE_USER_ID in str(new_item.get(key, "")):
                    new_item[key] = str(new_item[key]).replace(SOURCE_USER_ID, TEST_USER_ID)
            # NOTE: full_text_s3_key intentionally left pointing at source user's S3 path
            batch.put_item(Item=new_item)

    print(f"  Setup: cloned {len(items)} items from real user to test user")


def test(name):
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
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_token():
    client = boto3.client("cognito-idp", region_name="us-east-1")
    resp = client.initiate_auth(
        ClientId=COGNITO_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": TEST_USER_EMAIL, "PASSWORD": TEST_USER_PASSWORD},
    )
    return resp["AuthenticationResult"]["IdToken"]


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

@test("GET /feed returns 200 with cards")
def test_feed(token):
    r = requests.get(f"{API_URL}/feed", headers={"Authorization": token})
    assert r.status_code == 200, f"Got {r.status_code}: {r.text[:100]}"
    body = r.json()
    assert "cards" in body
    assert len(body["cards"]) > 0, "Expected cards (test user has cloned data)"
    # Verify new fields are present
    card = body["cards"][0]
    assert "read" in card
    assert "bookmarked" in card
    assert "rating" in card
    assert "view_count" in card


@test("GET /feed/{card_id} returns card detail")
def test_card_detail(token, card_id):
    r = requests.get(f"{API_URL}/feed/{card_id}", headers={"Authorization": token})
    assert r.status_code == 200, f"Got {r.status_code}: {r.text[:100]}"
    body = r.json()
    assert "hook" in body
    assert "digest" in body
    assert "paper_id" in body


@test("POST /engagement returns 201")
def test_engagement(token, card):
    r = requests.post(
        f"{API_URL}/engagement",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"paper_id": card["paper_id"], "card_id": card["card_id"], "action": "view"},
    )
    assert r.status_code == 201, f"Got {r.status_code}: {r.text[:100]}"


@test("POST /engagement bookmark persists on card")
def test_bookmark_persists(token, card):
    # Bookmark
    r = requests.post(
        f"{API_URL}/engagement",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"paper_id": card["paper_id"], "card_id": card["card_id"], "action": "bookmark", "section": "add"},
    )
    assert r.status_code == 201
    # Verify it's persisted
    r2 = requests.get(f"{API_URL}/feed/{card['card_id']}", headers={"Authorization": token})
    body = r2.json()
    assert body.get("bookmarked") == True, f"Expected bookmarked=True, got {body.get('bookmarked')}"


@test("POST /engagement rate persists on card")
def test_rate_persists(token, card):
    r = requests.post(
        f"{API_URL}/engagement",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"paper_id": card["paper_id"], "card_id": card["card_id"], "action": "rate", "rating": 5},
    )
    assert r.status_code == 201
    r2 = requests.get(f"{API_URL}/feed/{card['card_id']}", headers={"Authorization": token})
    body = r2.json()
    assert body.get("rating") == 5, f"Expected rating=5, got {body.get('rating')}"


@test("POST /engagement dismiss filters card from feed")
def test_dismiss_filters(token, cards):
    # Find a card that isn't the first one (so we don't break other tests)
    if len(cards) < 2:
        return  # Skip if not enough cards
    target = cards[-1]
    r = requests.post(
        f"{API_URL}/engagement",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"paper_id": target["paper_id"], "card_id": target["card_id"], "action": "dismiss"},
    )
    assert r.status_code == 201
    # Verify it's gone from feed
    r2 = requests.get(f"{API_URL}/feed", headers={"Authorization": token})
    card_ids = [c["card_id"] for c in r2.json()["cards"]]
    assert target["card_id"] not in card_ids, "Dismissed card still in feed"


@test("GET /chat/{paper_id} returns conversation history")
def test_chat_history(token, paper_id):
    r = requests.get(f"{API_URL}/chat/{paper_id}", headers={"Authorization": token})
    assert r.status_code == 200, f"Got {r.status_code}: {r.text[:100]}"
    body = r.json()
    assert "turns" in body
    assert len(body["turns"]) > 0, "Expected conversation turns (test user has cloned data)"


@test("CORS headers present on all endpoints")
def test_cors(token):
    for endpoint in ["/feed", "/engagement", "/chat"]:
        method = "GET" if endpoint != "/engagement" else "OPTIONS"
        r = requests.options(
            f"{API_URL}{endpoint}",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST" if endpoint != "/feed" else "GET"},
        )
        assert "access-control-allow-origin" in r.headers, f"No CORS on {endpoint}"


# ---------------------------------------------------------------------------
# Learn Step Test
# ---------------------------------------------------------------------------

@test("Learn step runs successfully with test user data")
def test_learn_step():
    from backend.shared import db
    from backend.pipeline.learn import handler

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table(TABLE_NAME)

    # Reset last_learn_ts to force a full run
    profile_meta = db.get_profile_meta(table, TEST_USER_ID)
    profile_meta["last_learn_ts"] = "2026-06-10T00:00:00Z"
    db.put_profile_meta(table, TEST_USER_ID, profile_meta)

    result = handler({"user_id": TEST_USER_ID, "table_name": TABLE_NAME}, None)

    assert result["status"] == "ok", f"Learn step failed: {result}"
    assert len(result["changes"]) > 0, "Expected at least one profile change"

    # Print the Learn output report
    print(f"\n{'─'*50}")
    print(f"  LEARN STEP REPORT")
    print(f"{'─'*50}")
    print(f"  Status: {result['status']}")
    print(f"  Changes: {result['changes']}")
    print(f"  Changelog: {result.get('changelog', '(none)')}")
    print()

    # Show updated profile
    profile = db.get_full_profile(table, TEST_USER_ID)
    print(f"  UPDATED AREAS:")
    for area in profile.get("areas", []):
        name = area.get("name", area.get("id", "?"))
        status = area.get("status", "?")
        frontier = str(area.get("frontier", ""))
        print(f"    [{status.upper():8s}] {name}")
        # Wrap frontier at ~80 chars
        while frontier:
            print(f"             {frontier[:80]}")
            frontier = frontier[80:]

    hyp = profile.get("hypothesis", {})
    if hyp.get("supporting") or hyp.get("refuting") or hyp.get("refining"):
        print(f"\n  HYPOTHESIS EVIDENCE:")
        for k in ("supporting", "refuting", "refining"):
            items = hyp.get(k, [])
            if items:
                print(f"    {k}:")
                for item in items:
                    print(f"      • {str(item)[:100]}")

    summaries = profile.get("summaries", [])
    active_summaries = [s for s in summaries if s.get("content") and s["content"] != "No activity yet."]
    if active_summaries:
        print(f"\n  SUMMARIES:")
        for s in sorted(active_summaries, key=lambda x: x.get("SK", "")):
            tier = s.get("tier", "?")
            content = str(s.get("content", ""))[:150]
            print(f"    [{tier}] {content}")

    print(f"{'─'*50}\n")


@test("Learn step writes frontier snapshots to history")
def test_learn_history():
    from backend.shared import db

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table(TABLE_NAME)

    # Check latest history event
    from boto3.dynamodb.conditions import Key
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{TEST_USER_ID}#PROFILE_HISTORY"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    assert len(items) > 0, "No profile history events found"
    latest = items[0]
    assert latest.get("type") == "learn_update"
    assert "frontier_snapshots" in latest, f"No frontier_snapshots in history: {list(latest.keys())}"

    # Print frontier diffs
    snapshots = latest.get("frontier_snapshots", {})
    if snapshots:
        print(f"\n{'─'*50}")
        print(f"  FRONTIER PROGRESSION (before → after)")
        print(f"{'─'*50}")
        for area_id, snap in snapshots.items():
            before = snap.get("before", {}).get("frontier", "(empty)")
            after = snap.get("after", {}).get("frontier", "(empty)")
            print(f"\n    {area_id}:")
            print(f"      BEFORE: {str(before)[:120]}")
            print(f"      AFTER:  {str(after)[:120]}")
        print(f"{'─'*50}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("\n=== Full Integration Test ===\n")
    print(f"Source user: {SOURCE_USER_ID}")
    print(f"Test user:   {TEST_USER_ID}")
    print(f"API:         {API_URL}")
    print()

    # Setup: clean slate then clone fresh data
    print("[Setup]")
    cleanup_test_data()
    create_test_data()
    print()

    try:
        # Auth
        print("[Auth]")
        token = get_token()
        print(f"  ✓ Got token")
        print()

        # API Tests
        print("[Feed API]")
        test_feed(token)

        r = requests.get(f"{API_URL}/feed?limit=5", headers={"Authorization": token})
        cards = r.json().get("cards", [])
        card = cards[0] if cards else None

        if card:
            test_card_detail(token, card["card_id"])
        print()

        print("[Engagement API]")
        if card:
            test_engagement(token, card)
            test_bookmark_persists(token, card)
            test_rate_persists(token, card)
            test_dismiss_filters(token, cards)
        print()

        print("[Chat API]")
        if card:
            test_chat_history(token, card["paper_id"])
        print()

        print("[CORS]")
        test_cors(token)
        print()

        print("[Learn Step]")
        test_learn_step()
        test_learn_history()
        print()

    finally:
        # Cleanup: always delete test data, even if tests fail/crash
        print("[Cleanup]")
        cleanup_test_data()
        print()

    # Summary
    total = passed + failed
    print(f"{'='*50}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  • {e}")
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

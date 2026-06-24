"""Fixtures for Sarathi integration tests.

These tests hit real deployed APIs using a real Cognito token for the TEST user.
Requires SARATHI_TEST_PASSWORD environment variable to be set.

Test user: 447844a8-c0e1-700b-2fdf-f9512eee3e49 (kunal@example.com)
Live user (data source): 00000000-0000-0000-0000-000000000000 (kunaljaura@gmail.com)
"""

import os

import boto3
import pytest
import requests
from boto3.dynamodb.conditions import Attr

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE_URL = "https://abcde12345.execute-api.us-east-1.amazonaws.com/prod"
COGNITO_USER_POOL_ID = "us-east-1_XXXXXXXXX"
COGNITO_CLIENT_ID = "your-cognito-app-client-id"
TEST_USER_EMAIL = "kunal@example.com"
TEST_USER_ID = "447844a8-c0e1-700b-2fdf-f9512eee3e49"
LIVE_USER_ID = "00000000-0000-0000-0000-000000000000"
TABLE_NAME = "sarathi"

# Max items to clone per category (keep setup fast)
MAX_FEED_CARDS = 5


# ---------------------------------------------------------------------------
# Pytest configuration
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests that hit real APIs")


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_password():
    """Get test password from environment or skip all tests."""
    password = os.environ.get("SARATHI_TEST_PASSWORD")
    if not password:
        pytest.skip("SARATHI_TEST_PASSWORD not set — skipping integration tests")
    return password


@pytest.fixture(scope="session")
def auth_token(test_password):
    """Authenticate via Cognito and return an ID token."""
    client = boto3.client("cognito-idp", region_name="us-east-1")
    resp = client.initiate_auth(
        ClientId=COGNITO_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": TEST_USER_EMAIL,
            "PASSWORD": test_password,
        },
    )
    return resp["AuthenticationResult"]["IdToken"]


@pytest.fixture(scope="session")
def api_url():
    """Return the API base URL."""
    return API_BASE_URL


@pytest.fixture(scope="session")
def headers(auth_token):
    """Return headers dict with Authorization and Content-Type."""
    return {
        "Authorization": auth_token,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# API client helper
# ---------------------------------------------------------------------------


class ApiClient:
    """Thin wrapper around requests with auth headers pre-set."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": token,
            "Content-Type": "application/json",
        })

    def get(self, path: str, **kwargs):
        return self.session.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path: str, **kwargs):
        return self.session.post(f"{self.base_url}{path}", **kwargs)

    def put(self, path: str, **kwargs):
        return self.session.put(f"{self.base_url}{path}", **kwargs)

    def delete(self, path: str, **kwargs):
        return self.session.delete(f"{self.base_url}{path}", **kwargs)


@pytest.fixture(scope="session")
def api(auth_token, api_url):
    """Return an ApiClient instance for making authenticated requests."""
    return ApiClient(api_url, auth_token)


# ---------------------------------------------------------------------------
# Test data setup / teardown
# ---------------------------------------------------------------------------


def _get_table():
    """Get DynamoDB table resource."""
    session = boto3.Session(region_name="us-east-1")
    dynamodb = session.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def _scan_user_items(table, user_id):
    """Scan all DDB items for a given user."""
    prefix = f"USER#{user_id}"
    items = []
    response = table.scan(FilterExpression=Attr("PK").begins_with(prefix))
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.scan(
            FilterExpression=Attr("PK").begins_with(prefix),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))
    return items


def _cleanup_test_user(table):
    """Delete ALL data for the test user. Idempotent."""
    items = _scan_user_items(table, TEST_USER_ID)

    # Also delete SYSTEM#USERS entry for test user
    try:
        table.delete_item(Key={"PK": "SYSTEM#USERS", "SK": f"USER#{TEST_USER_ID}"})
    except Exception:
        pass

    if items:
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    return len(items)


def _clone_data_to_test_user(table):
    """Clone a subset of data from the live user to the test user.

    Clones:
    - Profile META + area items
    - A few feed cards (up to MAX_FEED_CARDS)
    - SYSTEM#USERS registration

    Returns dict with card_ids and paper_ids for tests to reference.
    """
    source_items = _scan_user_items(table, LIVE_USER_ID)

    # Categorize items by SK pattern
    profile_items = []
    feed_items = []
    chat_items = []

    for item in source_items:
        sk = item.get("SK", "")
        if sk.startswith("PROFILE#") or sk == "META":
            profile_items.append(item)
        elif sk.startswith("FEED#") or sk.startswith("CARD#"):
            feed_items.append(item)
        elif sk.startswith("CHAT#") or sk.startswith("CONV#"):
            chat_items.append(item)

    # Limit feed items
    feed_items = feed_items[:MAX_FEED_CARDS]
    # Take a couple chat items if available (for chat history test)
    chat_items = chat_items[:3]

    items_to_clone = profile_items + feed_items + chat_items
    card_ids = []
    paper_ids = []

    with table.batch_writer() as batch:
        for item in items_to_clone:
            new_item = dict(item)
            # Replace user ID in PK
            new_item["PK"] = item["PK"].replace(LIVE_USER_ID, TEST_USER_ID)
            # Replace in user_id field
            if "user_id" in new_item:
                new_item["user_id"] = TEST_USER_ID
            # Fix GSI keys that contain user_id
            for key in ("gsi1pk", "gsi2pk", "gsi3pk", "gsi4pk"):
                if key in new_item and LIVE_USER_ID in str(new_item.get(key, "")):
                    new_item[key] = str(new_item[key]).replace(LIVE_USER_ID, TEST_USER_ID)
            batch.put_item(Item=new_item)

            # Track card_ids and paper_ids
            sk = new_item.get("SK", "")
            if sk.startswith("FEED#") or sk.startswith("CARD#"):
                cid = new_item.get("card_id")
                pid = new_item.get("paper_id")
                if cid:
                    card_ids.append(cid)
                if pid and pid not in paper_ids:
                    paper_ids.append(pid)

        # Register test user in SYSTEM#USERS
        batch.put_item(Item={
            "PK": "SYSTEM#USERS",
            "SK": f"USER#{TEST_USER_ID}",
            "user_id": TEST_USER_ID,
            "email": TEST_USER_EMAIL,
            "status": "active",
        })

    return {
        "card_ids": card_ids,
        "paper_ids": paper_ids,
        "total_cloned": len(items_to_clone),
    }


@pytest.fixture(scope="session")
def setup_test_data(test_password):
    """Session-scoped fixture: clone data from live user, yield info, then cleanup.

    Depends on test_password so it only runs when credentials are available.
    """
    table = _get_table()

    # Setup: clean slate then clone
    _cleanup_test_user(table)
    result = _clone_data_to_test_user(table)

    yield result

    # Teardown: remove all test user data
    _cleanup_test_user(table)

"""DynamoDB access layer for Sārathi single-table design.

All functions take a boto3 DynamoDB Table resource as the first parameter.
The caller is responsible for creating the table resource and passing it in.

PK/SK patterns:
  Profile:         PK=USER#<sub>#PROFILE,           SK=META|AREA#<id>|HYPOTHESIS|SUMMARY#<tier>
  Paper:           PK=USER#<sub>#PAPER#<paper_id>,  SK=META
  Feed:            PK=USER#<sub>#FEED,              SK=CARD#<card_id>
  Library:         PK=USER#<sub>#LIBRARY#<paper_id>,SK=META
  Engagement:      PK=USER#<sub>#ENGAGEMENT,        SK=TS#<iso_ts>
  Profile History: PK=USER#<sub>#PROFILE_HISTORY,   SK=TS#<iso_ts>
  Conversation:    PK=USER#<sub>#CONV#<conv_id>,    SK=META|TURN#<seq>
  Conv Archive:    PK=USER#<sub>#CONV_ARCHIVE#<conv_id>#<batch_id>, SK=TURN#<seq>

GSIs (sparse, using gsiNpk/gsiNsk attributes):
  GSI1: list conversations   PK=USER#<sub>,                          SK=CONV#<conv_id>
  GSI2: papers by status     PK=USER#<sub>#PAPER_STATUS#<status>,    SK=TS#<discovered_at>
  GSI3: library entries      PK=USER#<sub>#LIBRARY,                  SK=TS#<read_at>
  GSI4: engagement per paper PK=USER#<sub>#PAPER_ENGAGEMENT#<paper_id>, SK=TS#<iso_ts>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from boto3.dynamodb.conditions import Key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """UTC ISO timestamp with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _sanitize_item(item: dict) -> dict:
    """Prepare a dict for DDB: convert floats to Decimal, remove None values."""
    cleaned = {}
    for k, v in item.items():
        if v is None:
            continue
        elif isinstance(v, float):
            cleaned[k] = Decimal(str(v))
        elif isinstance(v, dict):
            cleaned[k] = _sanitize_item(v)
        elif isinstance(v, list):
            cleaned[k] = [
                _sanitize_item(i) if isinstance(i, dict)
                else Decimal(str(i)) if isinstance(i, float)
                else i
                for i in v if i is not None
            ]
        else:
            cleaned[k] = v
    return cleaned


def _profile_pk(user_id: str) -> str:
    return f"USER#{user_id}#PROFILE"


def _paper_pk(user_id: str, paper_id: str) -> str:
    return f"USER#{user_id}#PAPER#{paper_id}"


def _feed_pk(user_id: str) -> str:
    return f"USER#{user_id}#FEED"


def _library_pk(user_id: str, paper_id: str) -> str:
    return f"USER#{user_id}#LIBRARY#{paper_id}"


def _engagement_pk(user_id: str) -> str:
    return f"USER#{user_id}#ENGAGEMENT"


def _profile_history_pk(user_id: str) -> str:
    return f"USER#{user_id}#PROFILE_HISTORY"


def _conv_pk(user_id: str, conv_id: str) -> str:
    return f"USER#{user_id}#CONV#{conv_id}"


def _conv_archive_pk(user_id: str, conv_id: str, batch_id: str) -> str:
    return f"USER#{user_id}#CONV_ARCHIVE#{conv_id}#{batch_id}"


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def get_full_profile(table, user_id: str) -> dict:
    """Query all items under the PROFILE PK.

    Returns a dict with keys: meta, areas, hypothesis, summaries.
    Each is populated from matching SK items.
    """
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(_profile_pk(user_id)),
    )
    items = resp.get("Items", [])

    result: dict[str, Any] = {
        "meta": None,
        "areas": [],
        "hypothesis": None,
        "summaries": [],
    }
    for item in items:
        sk = item.get("SK", "")
        if sk == "META":
            result["meta"] = item
        elif sk.startswith("AREA#"):
            result["areas"].append(item)
        elif sk == "HYPOTHESIS":
            result["hypothesis"] = item
        elif sk.startswith("SUMMARY#"):
            result["summaries"].append(item)
    return result


def get_profile_meta(table, user_id: str) -> Optional[dict]:
    """GetItem for profile META."""
    resp = table.get_item(
        Key={"PK": _profile_pk(user_id), "SK": "META"},
    )
    return resp.get("Item")


def get_profile_areas(table, user_id: str) -> list[dict]:
    """Query all AREA# items under the profile PK."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(_profile_pk(user_id))
            & Key("SK").begins_with("AREA#")
        ),
    )
    return resp.get("Items", [])


def put_profile_meta(table, user_id: str, meta: dict) -> None:
    """Write (or overwrite) the profile META item.

    Expects meta to contain fields like learning_style, reading_speed, paper_goal.
    """
    item = {
        "PK": _profile_pk(user_id),
        "SK": "META",
        "user_id": user_id,
        "last_updated": _now_iso(),
        **meta,
    }
    table.put_item(Item=_sanitize_item(item))


def put_profile_area(table, user_id: str, area: dict) -> None:
    """Write (or overwrite) a single AREA item.

    area must include 'id' (the area_id used in the SK).
    """
    area_id = area["id"]
    item = {
        "PK": _profile_pk(user_id),
        "SK": f"AREA#{area_id}",
        "user_id": user_id,
        **area,
    }
    if "added_at" not in item or item["added_at"] is None:
        item["added_at"] = _now_iso()
    table.put_item(Item=_sanitize_item(item))


def put_profile_hypothesis(table, user_id: str, hypothesis: dict) -> None:
    """Write (or overwrite) the HYPOTHESIS item."""
    item = {
        "PK": _profile_pk(user_id),
        "SK": "HYPOTHESIS",
        "user_id": user_id,
        **hypothesis,
    }
    table.put_item(Item=_sanitize_item(item))


def put_profile_summary(table, user_id: str, tier: str, content: str) -> None:
    """Write (or overwrite) a SUMMARY item for the given tier.

    Tiers: yesterday, 3_day, 7_day, month, quarter.
    """
    item = {
        "PK": _profile_pk(user_id),
        "SK": f"SUMMARY#{tier}",
        "user_id": user_id,
        "tier": tier,
        "content": content,
        "updated_at": _now_iso(),
    }
    table.put_item(Item=_sanitize_item(item))


# ---------------------------------------------------------------------------
# Paper
# ---------------------------------------------------------------------------

def get_paper(table, user_id: str, paper_id: str) -> Optional[dict]:
    """GetItem for a paper's META record."""
    resp = table.get_item(
        Key={"PK": _paper_pk(user_id, paper_id), "SK": "META"},
    )
    return resp.get("Item")


def put_paper(table, user_id: str, paper: dict) -> None:
    """Write (or overwrite) a paper item.

    paper must include 'id' (paper_id). Automatically writes GSI2
    attributes for querying papers by status.
    """
    paper_id = paper["id"]
    status = paper.get("status", "candidate")
    discovered_at = paper.get("discovered_at") or _now_iso()

    item = {
        **paper,
        "PK": _paper_pk(user_id, paper_id),
        "SK": "META",
        "user_id": user_id,
        "discovered_at": discovered_at,
        # GSI2: papers by status, newest first (MUST come after **paper to win)
        "gsi2pk": f"USER#{user_id}#PAPER_STATUS#{status}",
        "gsi2sk": f"TS#{discovered_at}",
    }
    table.put_item(Item=_sanitize_item(item))


def paper_exists(table, user_id: str, paper_id: str) -> bool:
    """Check if a paper record already exists (for dedup in pipeline)."""
    resp = table.get_item(
        Key={"PK": _paper_pk(user_id, paper_id), "SK": "META"},
        ProjectionExpression="PK",
    )
    return "Item" in resp


def list_papers_by_status(
    table, user_id: str, status: str, limit: int = 20
) -> list[dict]:
    """Query GSI2 for papers with a given status, newest first."""
    resp = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("gsi2pk").eq(
            f"USER#{user_id}#PAPER_STATUS#{status}"
        ),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------

def put_feed_card(table, user_id: str, card: dict) -> None:
    """Write a feed card item.

    card must include 'card_id'. card_id should contain a timestamp prefix
    for natural sort ordering (e.g., '20260615T023000Z_abc123').
    """
    card_id = card["card_id"]
    item = {
        "PK": _feed_pk(user_id),
        "SK": f"CARD#{card_id}",
        "user_id": user_id,
        **card,
    }
    if "created_at" not in item or item["created_at"] is None:
        item["created_at"] = _now_iso()
    table.put_item(Item=_sanitize_item(item))


def update_feed_card_meta(table, user_id: str, card_id: str, updates: dict) -> None:
    """Update specific fields on a feed card (bookmark, rating, etc.)."""
    expr_parts = []
    attr_names = {}
    attr_values = {}
    for i, (key, value) in enumerate(updates.items()):
        alias = f"#k{i}"
        val_alias = f":v{i}"
        expr_parts.append(f"{alias} = {val_alias}")
        attr_names[alias] = key
        attr_values[val_alias] = value

    table.update_item(
        Key={"PK": _feed_pk(user_id), "SK": f"CARD#{card_id}"},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=_sanitize_item(attr_values),
    )


def list_feed_cards(
    table, user_id: str, limit: int = 20, last_key: Optional[dict] = None
) -> tuple[list[dict], Optional[dict]]:
    """Query feed cards, newest first (paginated).

    Returns (items, next_last_key). next_last_key is None when no more pages.
    card_id includes a timestamp prefix so descending SK order = newest first.
    """
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": (
            Key("PK").eq(_feed_pk(user_id))
            & Key("SK").begins_with("CARD#")
        ),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if last_key:
        kwargs["ExclusiveStartKey"] = last_key

    resp = table.query(**kwargs)
    items = resp.get("Items", [])
    next_key = resp.get("LastEvaluatedKey")
    return items, next_key


def get_feed_card(table, user_id: str, card_id: str) -> Optional[dict]:
    """GetItem for a specific feed card."""
    resp = table.get_item(
        Key={"PK": _feed_pk(user_id), "SK": f"CARD#{card_id}"},
    )
    return resp.get("Item")


# ---------------------------------------------------------------------------
# Engagement
# ---------------------------------------------------------------------------

def put_engagement_event(table, user_id: str, event: dict) -> None:
    """Write an engagement event.

    event must include 'ts' (high-resolution ISO timestamp) and 'paper_id'.
    Automatically writes GSI4 attributes for per-paper engagement queries.
    """
    ts = event["ts"]
    paper_id = event["paper_id"]

    item = {
        "PK": _engagement_pk(user_id),
        "SK": f"TS#{ts}",
        "user_id": user_id,
        # GSI4: engagement per paper
        "gsi4pk": f"USER#{user_id}#PAPER_ENGAGEMENT#{paper_id}",
        "gsi4sk": f"TS#{ts}",
        **event,
    }
    table.put_item(Item=_sanitize_item(item))


def list_engagement_events(
    table, user_id: str, start_ts: str, end_ts: str
) -> list[dict]:
    """Query engagement events in a time range (inclusive).

    start_ts and end_ts are ISO timestamps (e.g., '2026-06-10T00:00:00Z').
    """
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(_engagement_pk(user_id))
            & Key("SK").between(f"TS#{start_ts}", f"TS#{end_ts}")
        ),
    )
    return resp.get("Items", [])


def get_read_paper_ids(table, user_id: str) -> set[str]:
    """Return set of paper_ids that have a 'read' engagement event.

    Scans all engagement events — acceptable for one user with low volume.
    """
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(_engagement_pk(user_id)),
    )
    read_ids: set[str] = set()
    for item in resp.get("Items", []):
        if item.get("action") == "read":
            read_ids.add(item.get("paper_id", ""))
    return read_ids


# ---------------------------------------------------------------------------
# Profile History
# ---------------------------------------------------------------------------

def put_profile_history_event(table, user_id: str, event: dict) -> None:
    """Append a profile history event.

    event must include 'ts' (ISO timestamp).
    """
    ts = event.get("ts") or _now_iso()
    item = {
        "PK": _profile_history_pk(user_id),
        "SK": f"TS#{ts}",
        "user_id": user_id,
        "ts": ts,
        **event,
    }
    table.put_item(Item=_sanitize_item(item))


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

def get_conversation_by_paper(table, user_id: str, paper_id: str) -> Optional[dict]:
    """Find the conversation META for a given paper (conv_id = paper_id convention)."""
    resp = table.get_item(
        Key={"PK": _conv_pk(user_id, paper_id), "SK": "META"},
    )
    return resp.get("Item")


def create_conversation(
    table, user_id: str, paper_id: str, full_text_s3_key: str
) -> dict:
    """Create a new conversation for a paper. conv_id = paper_id."""
    item = {
        "PK": _conv_pk(user_id, paper_id),
        "SK": "META",
        "user_id": user_id,
        "conv_id": paper_id,
        "scope": "paper",
        "paper_id": paper_id,
        "full_text_s3_key": full_text_s3_key,
        "created_at": _now_iso(),
        "last_active": _now_iso(),
        "turn_count": 0,
        "gsi1pk": f"USER#{user_id}",
        "gsi1sk": f"CONV#{paper_id}",
    }
    table.put_item(Item=_sanitize_item(item))
    return item


def get_conversation_turns(table, user_id: str, conv_id: str) -> list[dict]:
    """Get all turns for a conversation, ordered by sequence."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(_conv_pk(user_id, conv_id))
            & Key("SK").begins_with("TURN#")
        ),
        ScanIndexForward=True,
    )
    return resp.get("Items", [])


def put_turn(
    table, user_id: str, conv_id: str, seq: int, request: str, request_ts: str
) -> None:
    """Write a new turn with request only (response filled later)."""
    item = {
        "PK": _conv_pk(user_id, conv_id),
        "SK": f"TURN#{seq:05d}",
        "user_id": user_id,
        "conv_id": conv_id,
        "seq": seq,
        "request": request,
        "request_ts": request_ts,
    }
    table.put_item(Item=_sanitize_item(item))


def update_turn_response(
    table,
    user_id: str,
    conv_id: str,
    seq: int,
    response: str,
    response_ts: str,
    citations: list[str],
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Fill in the response on an existing turn item."""
    table.update_item(
        Key={"PK": _conv_pk(user_id, conv_id), "SK": f"TURN#{seq:05d}"},
        UpdateExpression=(
            "SET #resp = :resp, response_ts = :rts, citations = :cit, "
            "tokens_in = :tin, tokens_out = :tout"
        ),
        ExpressionAttributeNames={"#resp": "response"},
        ExpressionAttributeValues={
            ":resp": response,
            ":rts": response_ts,
            ":cit": citations,
            ":tin": tokens_in,
            ":tout": tokens_out,
        },
    )


def update_conversation_last_active(table, user_id: str, conv_id: str) -> None:
    """Bump the last_active timestamp and turn_count on conversation META."""
    table.update_item(
        Key={"PK": _conv_pk(user_id, conv_id), "SK": "META"},
        UpdateExpression="SET last_active = :la ADD turn_count :one",
        ExpressionAttributeValues={
            ":la": _now_iso(),
            ":one": 1,
        },
    )

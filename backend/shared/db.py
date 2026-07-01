"""DynamoDB access layer for Sārathi single-table design.

All functions take a boto3 DynamoDB Table resource as the first parameter.
The caller is responsible for creating the table resource and passing it in.

Workspaces:
  Every workspace-scoped function REQUIRES an explicit ``workspace_id`` param.
  - When ``workspace_id`` is a non-empty string (KSUID), the PK contains
    ``#WS#<workspace_id>`` and that workspace's data is read/written.
  - When ``workspace_id`` is an empty string, legacy (pre-workspace) PKs are
    used. This is intentional and supports backward compatibility for tests
    and read-only access to data written before the workspace migration. New
    production code paths must always pass a real workspace_id.

PK/SK patterns (workspace-scoped, when workspace_id is set):
  Profile:         PK=USER#<sub>#WS#<wid>#PROFILE,             SK=META|AREA#<id>|HYPOTHESIS|SUMMARY#<tier>
  Paper:           PK=USER#<sub>#WS#<wid>#PAPER#<paper_id>,    SK=META
  Feed:            PK=USER#<sub>#WS#<wid>#FEED,                SK=CARD#<card_id>
  Library:         PK=USER#<sub>#WS#<wid>#LIBRARY#<paper_id>,  SK=META
  Engagement:      PK=USER#<sub>#WS#<wid>#ENGAGEMENT,          SK=TS#<iso_ts>
  Profile History: PK=USER#<sub>#WS#<wid>#PROFILE_HISTORY,     SK=TS#<iso_ts>
  Conversation:    PK=USER#<sub>#WS#<wid>#CONV#<conv_id>,      SK=META|TURN#<seq>
  Conv Archive:    PK=USER#<sub>#WS#<wid>#CONV_ARCHIVE#<conv_id>#<batch_id>, SK=TURN#<seq>
  Brief:           PK=USER#<sub>#WS#<wid>#BRIEF,               SK=WEEK#<iso_date>
  Pipeline run:    PK=USER#<sub>#WS#<wid>#PIPELINE,            SK=LATEST

User-scoped (NOT workspace-scoped):
  User META:       PK=USER#<sub>#PROFILE,                      SK=META  (background, learning_style, etc.)
  Push Sub:        PK=USER#<sub>#PUSH,                         SK=SUB#<endpoint_hash>
  Workspaces:      PK=USER#<sub>#WORKSPACES,                   SK=WS#<wid>
  Settings:        PK=USER#<sub>#SETTINGS,                     SK=ACTIVE_WS|...
  Onboarding mark: PK=USER#<sub>#ONBOARDING,                   SK=META

System-scoped:
  User registry:   PK=SYSTEM#USERS,                            SK=USER#<sub>
  Global papers:   PK=PAPER#<paper_id>,                        SK=META

GSIs (sparse, using gsiNpk/gsiNsk attributes; workspace_id is injected):
  GSI1: list conversations   PK=USER#<sub>#WS#<wid>,                          SK=CONV#<conv_id>
  GSI2: papers by status     PK=USER#<sub>#WS#<wid>#PAPER_STATUS#<status>,    SK=TS#<discovered_at>
  GSI3: library entries      PK=USER#<sub>#WS#<wid>#LIBRARY,                  SK=TS#<read_at>
  GSI4: engagement per paper PK=USER#<sub>#WS#<wid>#PAPER_ENGAGEMENT#<paper_id>, SK=TS#<iso_ts>
"""

from __future__ import annotations

import hashlib
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


def _ws_segment(workspace_id: str) -> str:
    """Return ``#WS#<wid>`` if workspace_id is set, else empty string.

    Used to inject the workspace prefix into PKs and GSI attributes. When
    workspace_id is empty, returns an empty string so PKs remain in legacy
    (pre-migration) shape.
    """
    return f"#WS#{workspace_id}" if workspace_id else ""


def _profile_pk(user_id: str, workspace_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#PROFILE"


def _paper_pk(user_id: str, workspace_id: str, paper_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#PAPER#{paper_id}"


def _feed_pk(user_id: str, workspace_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#FEED"


def _library_pk(user_id: str, workspace_id: str, paper_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#LIBRARY#{paper_id}"


def _engagement_pk(user_id: str, workspace_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#ENGAGEMENT"


def _profile_history_pk(user_id: str, workspace_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#PROFILE_HISTORY"


def _conv_pk(user_id: str, workspace_id: str, conv_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#CONV#{conv_id}"


def _conv_archive_pk(user_id: str, workspace_id: str, conv_id: str, batch_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#CONV_ARCHIVE#{conv_id}#{batch_id}"


def _brief_pk(user_id: str, workspace_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#BRIEF"


def _pipeline_pk(user_id: str, workspace_id: str) -> str:
    return f"USER#{user_id}{_ws_segment(workspace_id)}#PIPELINE"


def _global_paper_pk(paper_id: str) -> str:
    return f"PAPER#{paper_id}"


def _gsi_user_scope(user_id: str, workspace_id: str) -> str:
    """Return the workspace-scoped GSI partition prefix for a user."""
    return f"USER#{user_id}{_ws_segment(workspace_id)}"


# ---------------------------------------------------------------------------
# User-level META (background, learning_style — not per-workspace)
# ---------------------------------------------------------------------------

def get_user_meta(table, user_id: str) -> Optional[dict]:
    """Get the user-level META item.

    User-level fields: ``learning_style``, ``background``, ``math_comfort``,
    ``time_per_week``, ``paper_preference``. These travel with the user, not
    with any individual workspace.
    """
    resp = table.get_item(Key={"PK": f"USER#{user_id}#PROFILE", "SK": "META"})
    return resp.get("Item")


def put_user_meta(table, user_id: str, meta: dict) -> None:
    """Write (or overwrite) the user-level META item."""
    item = {
        "PK": f"USER#{user_id}#PROFILE",
        "SK": "META",
        "user_id": user_id,
        "last_updated": _now_iso(),
        **meta,
    }
    table.put_item(Item=_sanitize_item(item))


# ---------------------------------------------------------------------------
# Onboarding marker (records whether user-level onboarding is complete)
# ---------------------------------------------------------------------------

def get_user_onboarding_status(table, user_id: str) -> Optional[dict]:
    """Get the user-level onboarding status."""
    resp = table.get_item(
        Key={"PK": f"USER#{user_id}#ONBOARDING", "SK": "META"},
    )
    return resp.get("Item")


def set_user_onboarding_complete(table, user_id: str) -> None:
    """Mark user-level onboarding as complete."""
    table.put_item(Item={
        "PK": f"USER#{user_id}#ONBOARDING",
        "SK": "META",
        "user_id": user_id,
        "user_onboarding_complete": True,
        "completed_at": _now_iso(),
    })


# ---------------------------------------------------------------------------
# Workspaces (registry + active pointer)
# ---------------------------------------------------------------------------

def list_workspaces(table, user_id: str) -> list[dict]:
    """List all workspace metadata records for a user."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"USER#{user_id}#WORKSPACES")
            & Key("SK").begins_with("WS#")
        ),
    )
    return resp.get("Items", [])


def create_workspace(
    table,
    user_id: str,
    workspace_id: str,
    name: str = "Default",
    description: str = "",
) -> dict:
    """Create a new workspace metadata record. Returns the item."""
    now = _now_iso()
    item = {
        "PK": f"USER#{user_id}#WORKSPACES",
        "SK": f"WS#{workspace_id}",
        "user_id": user_id,
        "workspace_id": workspace_id,
        "name": name,
        "description": description,
        "status": "active",
        "paused_reason": None,
        "created_at": now,
        "last_active_at": now,
    }
    table.put_item(Item=_sanitize_item(item))
    return item


def get_workspace(table, user_id: str, workspace_id: str) -> Optional[dict]:
    """Get a single workspace metadata record."""
    resp = table.get_item(
        Key={
            "PK": f"USER#{user_id}#WORKSPACES",
            "SK": f"WS#{workspace_id}",
        },
    )
    return resp.get("Item")


def update_workspace(
    table,
    user_id: str,
    workspace_id: str,
    **fields: Any,
) -> None:
    """Update mutable fields on a workspace metadata record.

    Allowed fields: name, description, status, paused_reason, last_active_at.
    """
    allowed = {"name", "description", "status", "paused_reason", "last_active_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return

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
        Key={
            "PK": f"USER#{user_id}#WORKSPACES",
            "SK": f"WS#{workspace_id}",
        },
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=_sanitize_item(attr_values),
    )


def archive_workspace(table, user_id: str, workspace_id: str) -> None:
    """Mark a workspace as archived (soft delete; mirrors pause pattern)."""
    update_workspace(
        table,
        user_id,
        workspace_id,
        status="archived",
        paused_reason="archived",
    )


def get_active_workspace(table, user_id: str) -> Optional[str]:
    """Return the currently active workspace_id for a user, or None."""
    resp = table.get_item(
        Key={"PK": f"USER#{user_id}#SETTINGS", "SK": "ACTIVE_WS"},
    )
    item = resp.get("Item")
    if not item:
        return None
    return item.get("workspace_id") or None


def set_active_workspace(table, user_id: str, workspace_id: str) -> None:
    """Set the user's active workspace pointer."""
    table.put_item(Item={
        "PK": f"USER#{user_id}#SETTINGS",
        "SK": "ACTIVE_WS",
        "user_id": user_id,
        "workspace_id": workspace_id,
        "updated_at": _now_iso(),
    })


# ---------------------------------------------------------------------------
# Profile (workspace-scoped: areas, hypothesis, summaries, paper_goal)
# ---------------------------------------------------------------------------

def get_full_profile(table, user_id: str, workspace_id: str) -> dict:
    """Query all items under the workspace's PROFILE PK.

    Returns a dict with keys: meta, areas, hypothesis, summaries.
    """
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(_profile_pk(user_id, workspace_id)),
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


def get_profile_meta(table, user_id: str, workspace_id: str) -> Optional[dict]:
    """GetItem for workspace profile META (paper_goal, hypothesis_brief, etc.)."""
    resp = table.get_item(
        Key={"PK": _profile_pk(user_id, workspace_id), "SK": "META"},
    )
    return resp.get("Item")


def get_profile_areas(table, user_id: str, workspace_id: str) -> list[dict]:
    """Query all AREA# items under the workspace's profile PK."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(_profile_pk(user_id, workspace_id))
            & Key("SK").begins_with("AREA#")
        ),
    )
    return resp.get("Items", [])


def put_profile_meta(table, user_id: str, workspace_id: str, meta: dict) -> None:
    """Write (or overwrite) the workspace profile META item."""
    item = {
        "PK": _profile_pk(user_id, workspace_id),
        "SK": "META",
        "user_id": user_id,
        "last_updated": _now_iso(),
        **meta,
    }
    table.put_item(Item=_sanitize_item(item))


def put_profile_area(table, user_id: str, workspace_id: str, area: dict) -> None:
    """Write (or overwrite) a single AREA item.

    area must include 'id' (the area_id used in the SK).
    """
    area_id = area["id"]
    item = {
        "PK": _profile_pk(user_id, workspace_id),
        "SK": f"AREA#{area_id}",
        "user_id": user_id,
        **area,
    }
    if "added_at" not in item or item["added_at"] is None:
        item["added_at"] = _now_iso()
    table.put_item(Item=_sanitize_item(item))


def put_profile_hypothesis(table, user_id: str, workspace_id: str, hypothesis: dict) -> None:
    """Write (or overwrite) the HYPOTHESIS item."""
    item = {
        "PK": _profile_pk(user_id, workspace_id),
        "SK": "HYPOTHESIS",
        "user_id": user_id,
        **hypothesis,
    }
    table.put_item(Item=_sanitize_item(item))


def put_profile_summary(table, user_id: str, workspace_id: str, tier: str, content: str) -> None:
    """Write (or overwrite) a SUMMARY item for the given tier."""
    item = {
        "PK": _profile_pk(user_id, workspace_id),
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

def get_paper(table, user_id: str, workspace_id: str, paper_id: str) -> Optional[dict]:
    """GetItem for a paper's META record."""
    resp = table.get_item(
        Key={"PK": _paper_pk(user_id, workspace_id, paper_id), "SK": "META"},
    )
    return resp.get("Item")


def put_paper(table, user_id: str, workspace_id: str, paper: dict) -> None:
    """Write (or overwrite) a paper item."""
    paper_id = paper["id"]
    status = paper.get("status", "candidate")
    discovered_at = paper.get("discovered_at") or _now_iso()

    item = {
        **paper,
        "PK": _paper_pk(user_id, workspace_id, paper_id),
        "SK": "META",
        "user_id": user_id,
        "discovered_at": discovered_at,
        # GSI2: papers by status, newest first (workspace-scoped)
        "gsi2pk": f"{_gsi_user_scope(user_id, workspace_id)}#PAPER_STATUS#{status}",
        "gsi2sk": f"TS#{discovered_at}",
    }
    table.put_item(Item=_sanitize_item(item))


def paper_exists(table, user_id: str, workspace_id: str, paper_id: str) -> bool:
    """Check if a paper record already exists (for dedup in pipeline)."""
    resp = table.get_item(
        Key={"PK": _paper_pk(user_id, workspace_id, paper_id), "SK": "META"},
        ProjectionExpression="PK",
    )
    return "Item" in resp


def list_papers_by_status(
    table, user_id: str, workspace_id: str, status: str, limit: int = 20
) -> list[dict]:
    """Query GSI2 for papers with a given status, newest first."""
    resp = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("gsi2pk").eq(
            f"{_gsi_user_scope(user_id, workspace_id)}#PAPER_STATUS#{status}"
        ),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------

def put_feed_card(table, user_id: str, workspace_id: str, card: dict) -> None:
    """Write a feed card item."""
    card_id = card["card_id"]
    item = {
        "PK": _feed_pk(user_id, workspace_id),
        "SK": f"CARD#{card_id}",
        "user_id": user_id,
        **card,
    }
    if "created_at" not in item or item["created_at"] is None:
        item["created_at"] = _now_iso()
    table.put_item(Item=_sanitize_item(item))


def update_feed_card_meta(
    table, user_id: str, workspace_id: str, card_id: str, updates: dict
) -> None:
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
        Key={"PK": _feed_pk(user_id, workspace_id), "SK": f"CARD#{card_id}"},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=_sanitize_item(attr_values),
    )


def list_feed_cards(
    table,
    user_id: str,
    workspace_id: str,
    limit: int = 20,
    last_key: Optional[dict] = None,
) -> tuple[list[dict], Optional[dict]]:
    """Query feed cards, newest first (paginated)."""
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": (
            Key("PK").eq(_feed_pk(user_id, workspace_id))
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


def get_feed_card(table, user_id: str, workspace_id: str, card_id: str) -> Optional[dict]:
    """GetItem for a specific feed card."""
    resp = table.get_item(
        Key={"PK": _feed_pk(user_id, workspace_id), "SK": f"CARD#{card_id}"},
    )
    return resp.get("Item")


def get_feed_card_by_paper(
    table, user_id: str, workspace_id: str, paper_id: str
) -> Optional[dict]:
    """Get the most recent feed card for a given paper_id."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(_feed_pk(user_id, workspace_id))
            & Key("SK").begins_with("CARD#")
        ),
        FilterExpression="paper_id = :pid",
        ExpressionAttributeValues={":pid": paper_id},
        ScanIndexForward=False,
        Limit=5,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


# ---------------------------------------------------------------------------
# Engagement
# ---------------------------------------------------------------------------

def put_engagement_event(table, user_id: str, workspace_id: str, event: dict) -> None:
    """Write an engagement event."""
    ts = event["ts"]
    paper_id = event.get("paper_id")

    item = {
        "PK": _engagement_pk(user_id, workspace_id),
        "SK": f"TS#{ts}",
        "user_id": user_id,
        **event,
    }
    # Only add GSI4 keys if we have a paper_id (some events like impressions
    # aren't scoped to a specific paper).
    if paper_id:
        item["gsi4pk"] = f"{_gsi_user_scope(user_id, workspace_id)}#PAPER_ENGAGEMENT#{paper_id}"
        item["gsi4sk"] = f"TS#{ts}"
    table.put_item(Item=_sanitize_item(item))


def list_engagement_events(
    table, user_id: str, workspace_id: str, start_ts: str, end_ts: str
) -> list[dict]:
    """Query engagement events in a time range (inclusive)."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(_engagement_pk(user_id, workspace_id))
            & Key("SK").between(f"TS#{start_ts}", f"TS#{end_ts}")
        ),
    )
    return resp.get("Items", [])


def get_read_paper_ids(table, user_id: str, workspace_id: str) -> set[str]:
    """Return set of paper_ids that have a 'read' engagement event."""
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(_engagement_pk(user_id, workspace_id)),
    )
    read_ids: set[str] = set()
    for item in resp.get("Items", []):
        if item.get("action") == "read":
            read_ids.add(item.get("paper_id", ""))
    return read_ids


# ---------------------------------------------------------------------------
# Profile History
# ---------------------------------------------------------------------------

def put_profile_history_event(
    table, user_id: str, workspace_id: str, event: dict
) -> None:
    """Append a profile history event."""
    ts = event.get("ts") or _now_iso()
    item = {
        "PK": _profile_history_pk(user_id, workspace_id),
        "SK": f"TS#{ts}",
        "user_id": user_id,
        "ts": ts,
        **event,
    }
    table.put_item(Item=_sanitize_item(item))


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

def get_conversation_by_paper(
    table, user_id: str, workspace_id: str, paper_id: str
) -> Optional[dict]:
    """Find the conversation META for a given paper (conv_id = paper_id convention)."""
    resp = table.get_item(
        Key={"PK": _conv_pk(user_id, workspace_id, paper_id), "SK": "META"},
    )
    return resp.get("Item")


def create_conversation(
    table, user_id: str, workspace_id: str, paper_id: str, full_text_s3_key: str
) -> dict:
    """Create a new conversation for a paper. conv_id = paper_id."""
    item = {
        "PK": _conv_pk(user_id, workspace_id, paper_id),
        "SK": "META",
        "user_id": user_id,
        "conv_id": paper_id,
        "scope": "paper",
        "paper_id": paper_id,
        "full_text_s3_key": full_text_s3_key,
        "created_at": _now_iso(),
        "last_active": _now_iso(),
        "turn_count": 0,
        "gsi1pk": _gsi_user_scope(user_id, workspace_id),
        "gsi1sk": f"CONV#{paper_id}",
    }
    table.put_item(Item=_sanitize_item(item))
    return item


def create_research_conversation(
    table, user_id: str, workspace_id: str, conv_id: str, title: str = ""
) -> dict:
    """Create a free-form research conversation (not anchored to a paper)."""
    item = {
        "PK": _conv_pk(user_id, workspace_id, conv_id),
        "SK": "META",
        "user_id": user_id,
        "conv_id": conv_id,
        "scope": "research",
        "title": title or "New conversation",
        "created_at": _now_iso(),
        "last_active": _now_iso(),
        "turn_count": 0,
        "gsi1pk": _gsi_user_scope(user_id, workspace_id),
        "gsi1sk": f"CONV#{conv_id}",
    }
    table.put_item(Item=_sanitize_item(item))
    return item


def list_all_conversations(table, user_id: str, workspace_id: str) -> list[dict]:
    """List all conversations (paper + research) in this workspace, newest first."""
    resp = table.query(
        IndexName="GSI1",
        KeyConditionExpression=(
            Key("gsi1pk").eq(_gsi_user_scope(user_id, workspace_id))
            & Key("gsi1sk").begins_with("CONV#")
        ),
        ScanIndexForward=False,
    )
    return resp.get("Items", [])


def update_conversation_title(
    table, user_id: str, workspace_id: str, conv_id: str, title: str
) -> None:
    """Update the title of a conversation."""
    table.update_item(
        Key={"PK": _conv_pk(user_id, workspace_id, conv_id), "SK": "META"},
        UpdateExpression="SET title = :t",
        ExpressionAttributeValues={":t": title},
    )


def delete_conversation(
    table, user_id: str, workspace_id: str, conv_id: str
) -> None:
    """Delete a conversation and all its turns."""
    pk = _conv_pk(user_id, workspace_id, conv_id)
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(pk),
        ProjectionExpression="PK, SK",
    )
    with table.batch_writer() as batch:
        for item in resp.get("Items", []):
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})


def get_conversation_turns(
    table, user_id: str, workspace_id: str, conv_id: str
) -> list[dict]:
    """Get all turns for a conversation, ordered by sequence."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(_conv_pk(user_id, workspace_id, conv_id))
            & Key("SK").begins_with("TURN#")
        ),
        ScanIndexForward=True,
    )
    return resp.get("Items", [])


def put_turn(
    table,
    user_id: str,
    workspace_id: str,
    conv_id: str,
    seq: int,
    request: str,
    request_ts: str,
) -> None:
    """Write a new turn with request only (response filled later)."""
    item = {
        "PK": _conv_pk(user_id, workspace_id, conv_id),
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
    workspace_id: str,
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
        Key={"PK": _conv_pk(user_id, workspace_id, conv_id), "SK": f"TURN#{seq:05d}"},
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


def update_conversation_last_active(
    table, user_id: str, workspace_id: str, conv_id: str
) -> None:
    """Bump the last_active timestamp and turn_count on conversation META."""
    table.update_item(
        Key={"PK": _conv_pk(user_id, workspace_id, conv_id), "SK": "META"},
        UpdateExpression="SET last_active = :la ADD turn_count :one",
        ExpressionAttributeValues={
            ":la": _now_iso(),
            ":one": 1,
        },
    )


def pin_turn(
    table,
    user_id: str,
    workspace_id: str,
    conv_id: str,
    seq: int,
    pin_note: str = "",
) -> None:
    """Pin a conversation turn as a key insight."""
    update_expr = "SET pinned = :t, pinned_at = :ts"
    values: dict = {":t": True, ":ts": _now_iso()}
    if pin_note:
        update_expr += ", pin_note = :note"
        values[":note"] = pin_note
    table.update_item(
        Key={"PK": _conv_pk(user_id, workspace_id, conv_id), "SK": f"TURN#{seq:05d}"},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=values,
    )


def unpin_turn(
    table, user_id: str, workspace_id: str, conv_id: str, seq: int
) -> None:
    """Unpin a conversation turn."""
    table.update_item(
        Key={"PK": _conv_pk(user_id, workspace_id, conv_id), "SK": f"TURN#{seq:05d}"},
        UpdateExpression="REMOVE pinned, pinned_at, pin_note",
    )


def get_pinned_turns(
    table, user_id: str, workspace_id: str, conv_id: str
) -> list[dict]:
    """Get all pinned turns for a conversation."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(_conv_pk(user_id, workspace_id, conv_id))
            & Key("SK").begins_with("TURN#")
        ),
        FilterExpression="pinned = :t",
        ExpressionAttributeValues={":t": True},
    )
    return resp.get("Items", [])


def tag_paper(
    table,
    user_id: str,
    workspace_id: str,
    card_id: str,
    relevance: str,
    tags: list[str],
) -> None:
    """Set relevance level and tags on a feed card."""
    table.update_item(
        Key={"PK": _feed_pk(user_id, workspace_id), "SK": f"CARD#{card_id}"},
        UpdateExpression="SET relevance = :r, tags = :t, tagged_at = :ts",
        ExpressionAttributeValues={
            ":r": relevance,
            ":t": tags,
            ":ts": _now_iso(),
        },
    )


# ---------------------------------------------------------------------------
# Global Paper Registry
# ---------------------------------------------------------------------------

def get_global_paper(table, paper_id: str) -> Optional[dict]:
    """Get the global paper registry entry (shared across all users)."""
    resp = table.get_item(
        Key={"PK": _global_paper_pk(paper_id), "SK": "META"},
    )
    return resp.get("Item")


def put_global_paper(table, paper: dict) -> bool:
    """Write a global paper entry (first-writer-wins).

    Returns True if the item was written (new paper), False if it already existed.
    """
    paper_id = paper["paper_id"]
    item = {
        "PK": _global_paper_pk(paper_id),
        "SK": "META",
        "paper_id": paper_id,
        "discovered_at": _now_iso(),
        "embedded": False,
        **paper,
    }
    try:
        table.put_item(
            Item=_sanitize_item(item),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def mark_paper_embedded(table, paper_id: str, chunk_count: int) -> None:
    """Mark a paper as embedded in the global registry."""
    table.update_item(
        Key={"PK": _global_paper_pk(paper_id), "SK": "META"},
        UpdateExpression="SET embedded = :t, embedded_at = :ts, chunk_count = :c",
        ExpressionAttributeValues={
            ":t": True,
            ":ts": _now_iso(),
            ":c": chunk_count,
        },
    )


def is_paper_embedded(table, paper_id: str) -> bool:
    """Check if a paper has already been embedded."""
    resp = table.get_item(
        Key={"PK": _global_paper_pk(paper_id), "SK": "META"},
        ProjectionExpression="embedded",
    )
    item = resp.get("Item")
    return bool(item and item.get("embedded"))


def list_user_paper_ids(table, user_id: str, workspace_id: str) -> set[str]:
    """Get all paper_ids the user has in this workspace's feed."""
    pk = _feed_pk(user_id, workspace_id)
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(pk) & Key("SK").begins_with("CARD#")
        ),
        ProjectionExpression="paper_id",
    )
    paper_ids = set()
    for item in resp.get("Items", []):
        pid = item.get("paper_id", "")
        if pid:
            paper_ids.add(pid)
    while resp.get("LastEvaluatedKey"):
        resp = table.query(
            KeyConditionExpression=(
                Key("PK").eq(pk) & Key("SK").begins_with("CARD#")
            ),
            ProjectionExpression="paper_id",
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        for item in resp.get("Items", []):
            pid = item.get("paper_id", "")
            if pid:
                paper_ids.add(pid)
    return paper_ids


# ---------------------------------------------------------------------------
# Pipeline Run (deduplication, per workspace)
# ---------------------------------------------------------------------------


def get_pipeline_run(table, user_id: str, workspace_id: str) -> Optional[dict]:
    """Get the latest pipeline run record for dedup checks."""
    resp = table.get_item(
        Key={"PK": _pipeline_pk(user_id, workspace_id), "SK": "LATEST"},
    )
    return resp.get("Item")


def put_pipeline_run(
    table, user_id: str, workspace_id: str, execution_arn: str, status: str
) -> None:
    """Write/update the pipeline run record after starting a new execution."""
    table.put_item(Item={
        "PK": _pipeline_pk(user_id, workspace_id),
        "SK": "LATEST",
        "user_id": user_id,
        "workspace_id": workspace_id,
        "execution_arn": execution_arn,
        "status": status,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
    })


def update_pipeline_status(
    table, user_id: str, workspace_id: str, status: str
) -> None:
    """Update just the status + updated_at on an existing pipeline run record."""
    table.update_item(
        Key={"PK": _pipeline_pk(user_id, workspace_id), "SK": "LATEST"},
        UpdateExpression="SET #s = :s, updated_at = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":ts": _now_iso()},
    )


# ---------------------------------------------------------------------------
# Push Subscriptions (user-level, NOT workspace-scoped)
# ---------------------------------------------------------------------------


def put_push_subscription(table, user_id: str, subscription: dict) -> None:
    """Store a Web Push subscription for a user/device."""
    endpoint = subscription["endpoint"]
    endpoint_hash = hashlib.sha256(endpoint.encode()).hexdigest()[:16]
    table.put_item(Item={
        "PK": f"USER#{user_id}#PUSH",
        "SK": f"SUB#{endpoint_hash}",
        "endpoint": endpoint,
        "keys": subscription["keys"],
        "created_at": _now_iso(),
    })


def delete_push_subscription(table, user_id: str, endpoint: str) -> None:
    """Remove a push subscription (e.g., when endpoint returns 410 Gone)."""
    endpoint_hash = hashlib.sha256(endpoint.encode()).hexdigest()[:16]
    table.delete_item(Key={
        "PK": f"USER#{user_id}#PUSH",
        "SK": f"SUB#{endpoint_hash}",
    })


def list_push_subscriptions(table, user_id: str) -> list[dict]:
    """Get all push subscriptions for a user."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"USER#{user_id}#PUSH")
            & Key("SK").begins_with("SUB#")
        ),
    )
    return resp.get("Items", [])

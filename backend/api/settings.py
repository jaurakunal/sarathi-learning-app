"""API handler for user settings: pipeline pause/resume, account deletion.

Per-workspace pause/resume now operates on the active workspace metadata
record (USER#<sub>#WORKSPACES SK=WS#<wid>). The legacy SYSTEM#USERS.status
field is still updated as a global mirror so the fan-out can keep its
existing inactive-user check.
"""

from __future__ import annotations

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

from backend.shared import db
from backend.api._workspace_helper import get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


def handler(event: dict, context) -> dict:
    """
    GET /settings — return current settings (per-workspace + global)
    PUT /settings — update settings (pipeline_status; per-workspace by default)
        Body: {"pipeline_status": "paused"|"active", "scope": "workspace"|"all"}
    DELETE /account — delete all user data
    """
    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    method = event.get("httpMethod", "")
    path = event.get("path", "")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    if method == "PUT" and "/settings" in path:
        body = json.loads(event.get("body") or "{}")
        status = body.get("pipeline_status", body.get("status", "active"))
        if status not in ("active", "paused"):
            return _response(400, {"error": "status must be active or paused"})

        scope = body.get("scope", "workspace")  # default: only the active workspace

        if scope == "all":
            # Pause/resume every active (non-archived) workspace
            workspaces = db.list_workspaces(table, user_id)
            for ws in workspaces:
                wid = ws.get("workspace_id")
                if not wid or ws.get("status") == "archived":
                    continue
                paused_reason = "manual" if status == "paused" else None
                db.update_workspace(
                    table, user_id, wid,
                    status=status,
                    paused_reason=paused_reason,
                )
        else:
            wid = resolve_workspace_id(table, event, user_id)
            if not wid:
                return _response(400, {"error": "No active workspace"})
            paused_reason = "manual" if status == "paused" else None
            db.update_workspace(
                table, user_id, wid,
                status=status,
                paused_reason=paused_reason,
            )

        # Mirror to legacy SYSTEM#USERS so the fan-out's active-user filter still works.
        # If ALL workspaces are paused/archived, mark the user as paused; otherwise active.
        all_ws = db.list_workspaces(table, user_id)
        any_active = any(w.get("status") == "active" for w in all_ws)
        global_status = "active" if any_active else "paused"
        table.update_item(
            Key={"PK": "SYSTEM#USERS", "SK": f"USER#{user_id}"},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": global_status},
        )
        return _response(200, {"pipeline_status": status, "scope": scope})

    elif method == "DELETE" and "/account" in path:
        _delete_all_user_data(table, user_id)
        _delete_cognito_user(user_id)
        return _response(200, {"status": "deleted"})

    elif method == "GET":
        # Return both per-workspace status and global status
        resp = table.get_item(
            Key={"PK": "SYSTEM#USERS", "SK": f"USER#{user_id}"},
        )
        item = resp.get("Item", {})

        workspaces = db.list_workspaces(table, user_id)
        ws_status = []
        for ws in workspaces:
            ws_status.append({
                "workspace_id": ws.get("workspace_id", ""),
                "name": ws.get("name", ""),
                "status": ws.get("status", "active"),
                "paused_reason": ws.get("paused_reason", "") or "",
            })

        active_wid = db.get_active_workspace(table, user_id)
        active_ws = next((w for w in ws_status if w["workspace_id"] == active_wid), None)

        return _response(200, {
            "pipeline_status": active_ws["status"] if active_ws else item.get("status", "active"),
            "paused_reason": active_ws["paused_reason"] if active_ws else item.get("paused_reason", ""),
            "global_status": item.get("status", "active"),
            "workspaces": ws_status,
            "active_workspace_id": active_wid,
        })

    return _response(405, {"error": "Method not allowed"})


def _delete_cognito_user(user_id: str) -> None:
    """Delete the Cognito user account."""
    user_pool_id = os.environ.get("USER_POOL_ID", "")
    if not user_pool_id:
        logger.warning("USER_POOL_ID not set — cannot delete Cognito user")
        return
    try:
        cognito = boto3.client("cognito-idp")
        cognito.admin_delete_user(
            UserPoolId=user_pool_id,
            Username=user_id,
        )
        logger.info("Deleted Cognito user %s", user_id)
    except Exception:
        logger.exception("Failed to delete Cognito user %s", user_id)


def _delete_all_user_data(table, user_id: str) -> None:
    """Delete ALL data for a user across all PK patterns (legacy + per-workspace)."""
    # Static (non-workspace) prefixes
    base_prefixes = [
        f"USER#{user_id}#FEED",
        f"USER#{user_id}#PROFILE",
        f"USER#{user_id}#ENGAGEMENT",
        f"USER#{user_id}#PROFILE_HISTORY",
        f"USER#{user_id}#PUSH",
        f"USER#{user_id}#WORKSPACES",
        f"USER#{user_id}#SETTINGS",
        f"USER#{user_id}#ONBOARDING",
        f"USER#{user_id}#BRIEF",
        f"USER#{user_id}#PIPELINE",
    ]

    # Per-workspace prefixes (assumes WORKSPACES is read first)
    workspaces = db.list_workspaces(table, user_id)
    ws_prefixes: list[str] = []
    for ws in workspaces:
        wid = ws.get("workspace_id", "")
        if not wid:
            continue
        ws_prefixes += [
            f"USER#{user_id}#WS#{wid}#FEED",
            f"USER#{user_id}#WS#{wid}#PROFILE",
            f"USER#{user_id}#WS#{wid}#ENGAGEMENT",
            f"USER#{user_id}#WS#{wid}#PROFILE_HISTORY",
            f"USER#{user_id}#WS#{wid}#BRIEF",
            f"USER#{user_id}#WS#{wid}#PIPELINE",
        ]

    for pk in base_prefixes + ws_prefixes:
        resp = table.query(
            KeyConditionExpression=Key("PK").eq(pk),
            ProjectionExpression="PK, SK",
        )
        with table.batch_writer() as batch:
            for item in resp.get("Items", []):
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    # Conversations — find via GSI1 (legacy + each workspace's gsi1pk shape)
    gsi_prefixes = [f"USER#{user_id}"] + [
        f"USER#{user_id}#WS#{ws.get('workspace_id', '')}"
        for ws in workspaces
        if ws.get("workspace_id")
    ]
    for gsi_pk in gsi_prefixes:
        conv_resp = table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(gsi_pk),
            ProjectionExpression="conv_id, PK",
        )
        for conv in conv_resp.get("Items", []):
            pk = conv.get("PK", "")
            if not pk:
                continue
            items_resp = table.query(
                KeyConditionExpression=Key("PK").eq(pk),
                ProjectionExpression="PK, SK",
            )
            with table.batch_writer() as batch:
                for item in items_resp.get("Items", []):
                    batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    # Papers via GSI2 (legacy + per-workspace status partitions)
    paper_status_prefixes = [f"USER#{user_id}#PAPER_STATUS"] + [
        f"USER#{user_id}#WS#{ws.get('workspace_id', '')}#PAPER_STATUS"
        for ws in workspaces
        if ws.get("workspace_id")
    ]
    for prefix in paper_status_prefixes:
        for status in ("candidate", "triaged", "surfaced", "digested", "rejected", "skipped"):
            paper_resp = table.query(
                IndexName="GSI2",
                KeyConditionExpression=Key("gsi2pk").eq(f"{prefix}#{status}"),
                ProjectionExpression="PK, SK",
            )
            with table.batch_writer() as batch:
                for item in paper_resp.get("Items", []):
                    batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    # Remove from active users
    table.delete_item(Key={"PK": "SYSTEM#USERS", "SK": f"USER#{user_id}"})

    logger.info("Deleted all data for user %s", user_id)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,PUT,DELETE,OPTIONS",
        },
        "body": json.dumps(body),
    }

"""Confirm onboarding profile and save to DDB + register user for pipeline.

Two confirm paths:
  - stage="user": save user-level META (background/learning_style/etc.) and
    mark user-level onboarding complete.
  - stage="workspace" (default for backward compat): save workspace areas /
    hypothesis / paper_goal under the active workspace and trigger an initial
    pipeline run for that workspace.
"""

from __future__ import annotations

import json
import logging
import os

import boto3

from backend.shared import db
from backend.api._workspace_helper import get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


def handler(event: dict, context) -> dict:
    """POST /onboarding/confirm — save the confirmed profile.

    Body:
        {"stage": "user", "user_meta": {...}}
        {"stage": "workspace", "profile": {...}}  (legacy: stage may be omitted)
    """
    user_id = get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    body = json.loads(event.get("body") or "{}")
    stage = (body.get("stage") or "").strip().lower()

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    if stage == "user" or body.get("user_meta") and not body.get("profile"):
        return _confirm_user_meta(table, user_id, body)

    # Default: workspace stage (also covers legacy callers)
    return _confirm_workspace_profile(table, user_id, event, body)


def _confirm_user_meta(table, user_id: str, body: dict) -> dict:
    """Save the user-level META item."""
    user_meta = body.get("user_meta") or {}
    if not user_meta:
        return _response(400, {"error": "user_meta required"})

    payload = {
        "background": user_meta.get("background", ""),
        "learning_style": user_meta.get("learning_style", {}),
        "math_comfort": user_meta.get("math_comfort", ""),
        "paper_preference": user_meta.get("paper_preference", ""),
        "time_per_week": user_meta.get("time_per_week", ""),
    }
    db.put_user_meta(table, user_id, payload)
    db.set_user_onboarding_complete(table, user_id)

    return _response(200, {"status": "user_meta_saved"})


def _confirm_workspace_profile(table, user_id: str, event: dict, body: dict) -> dict:
    """Save the workspace profile and (optionally) trigger an initial pipeline."""
    profile = body.get("profile")
    if not profile:
        return _response(400, {"error": "profile required"})

    # Determine target workspace.
    workspace_id = (body.get("workspace_id") or "").strip()
    if not workspace_id:
        workspace_id = resolve_workspace_id(table, event, user_id) or ""

    # If still no workspace, create a Default one for this user.
    if not workspace_id:
        from backend.api.workspaces import _new_workspace_id
        workspace_id = _new_workspace_id()
        db.create_workspace(table, user_id, workspace_id, name="Default")
        db.set_active_workspace(table, user_id, workspace_id)

    # Save workspace meta (paper_goal + workspace_summary)
    meta_in = profile.get("meta", {}) or {}
    meta_item = {
        "paper_goal": meta_in.get("paper_goal", ""),
        "workspace_summary": meta_in.get("workspace_summary", ""),
    }
    # Legacy clients may also include learning_style / background here — promote
    # those to user-level META when the user-level META is not yet set.
    if not db.get_user_meta(table, user_id):
        legacy_user_meta = {}
        for k in ("background", "learning_style", "math_comfort", "paper_preference", "time_per_week"):
            if meta_in.get(k):
                legacy_user_meta[k] = meta_in[k]
        if legacy_user_meta:
            db.put_user_meta(table, user_id, legacy_user_meta)
            db.set_user_onboarding_complete(table, user_id)
    db.put_profile_meta(table, user_id, workspace_id, meta_item)

    # Save areas
    for area in profile.get("areas", []):
        db.put_profile_area(table, user_id, workspace_id, area)

    # Save hypothesis if present
    hypothesis = profile.get("hypothesis")
    if hypothesis and hypothesis.get("statement"):
        db.put_profile_hypothesis(table, user_id, workspace_id, hypothesis)

    # Register user in active users list (no-op if already there)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    table.put_item(Item={
        "PK": "SYSTEM#USERS",
        "SK": f"USER#{user_id}",
        "user_id": user_id,
        "registered_at": ts,
        "status": "active",
    })

    # Trigger initial pipeline run (per-workspace dedup)
    try:
        sfn = boto3.client("stepfunctions")
        state_machine_arn = os.environ.get("STATE_MACHINE_ARN", "")
        if state_machine_arn:
            can_trigger = True
            run = db.get_pipeline_run(table, user_id, workspace_id)
            if run and run.get("status") == "running":
                try:
                    desc = sfn.describe_execution(executionArn=run["execution_arn"])
                    if desc["status"] == "RUNNING":
                        can_trigger = False
                    else:
                        mapped = {"SUCCEEDED": "succeeded", "FAILED": "failed"}.get(
                            desc["status"], "failed"
                        )
                        db.update_pipeline_status(table, user_id, workspace_id, mapped)
                except Exception:
                    pass

            if can_trigger:
                resp_sfn = sfn.start_execution(
                    stateMachineArn=state_machine_arn,
                    input=json.dumps({
                        "user_id": user_id,
                        "workspace_id": workspace_id,
                        "table_name": TABLE_NAME,
                        "s3_bucket": os.environ.get("BUCKET_NAME", ""),
                        "since_days": 30,
                    }),
                )
                execution_arn = resp_sfn.get("executionArn", "")
                db.put_pipeline_run(table, user_id, workspace_id, execution_arn, "running")
                logger.info("Triggered initial pipeline for user %s ws %s", user_id, workspace_id)
            else:
                logger.info("Pipeline already running for user %s ws %s", user_id, workspace_id)
    except Exception:
        logger.exception("Failed to trigger initial pipeline — user can wait for nightly run")

    return _response(200, {
        "status": "confirmed",
        "user_id": user_id,
        "workspace_id": workspace_id,
    })


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }

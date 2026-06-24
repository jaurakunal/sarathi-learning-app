"""Confirm onboarding profile and save to DDB + register user for pipeline."""

from __future__ import annotations

import json
import logging
import os

import boto3

from backend.shared import db

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


def _get_user_id(event: dict) -> str:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    return claims.get("sub", "")


def handler(event: dict, context) -> dict:
    """POST /onboarding/confirm — save the confirmed profile and register user."""
    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    body = json.loads(event.get("body") or "{}")
    profile = body.get("profile")
    if not profile:
        return _response(400, {"error": "profile required"})

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    # Save profile meta
    meta = profile.get("meta", {})
    meta_item = {
        "learning_style": meta.get("learning_style", {}),
        "paper_goal": meta.get("paper_goal", ""),
        "background": meta.get("background", ""),
    }
    db.put_profile_meta(table, user_id, meta_item)

    # Save areas
    for area in profile.get("areas", []):
        db.put_profile_area(table, user_id, area)

    # Save hypothesis if present
    hypothesis = profile.get("hypothesis")
    if hypothesis and hypothesis.get("statement"):
        db.put_profile_hypothesis(table, user_id, hypothesis)

    # Register user in the active users list
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    table.put_item(Item={
        "PK": "SYSTEM#USERS",
        "SK": f"USER#{user_id}",
        "user_id": user_id,
        "registered_at": ts,
        "status": "active",
    })

    # Trigger initial pipeline run for this user (DDB-based dedup)
    try:
        sfn = boto3.client("stepfunctions")
        state_machine_arn = os.environ.get("STATE_MACHINE_ARN", "")
        if state_machine_arn:
            # DDB-based dedup check
            can_trigger = True
            run = db.get_pipeline_run(table, user_id)
            if run and run.get("status") == "running":
                # Verify with Step Functions
                try:
                    desc = sfn.describe_execution(executionArn=run["execution_arn"])
                    if desc["status"] == "RUNNING":
                        can_trigger = False
                    else:
                        mapped = {"SUCCEEDED": "succeeded", "FAILED": "failed"}.get(
                            desc["status"], "failed"
                        )
                        db.update_pipeline_status(table, user_id, mapped)
                except Exception:
                    pass  # Can't verify — assume stale, allow trigger

            if can_trigger:
                resp_sfn = sfn.start_execution(
                    stateMachineArn=state_machine_arn,
                    input=json.dumps({
                        "user_id": user_id,
                        "table_name": TABLE_NAME,
                        "s3_bucket": os.environ.get("BUCKET_NAME", ""),
                        "since_days": 30,
                    }),
                )
                execution_arn = resp_sfn.get("executionArn", "")
                db.put_pipeline_run(table, user_id, execution_arn, "running")
                logger.info("Triggered initial pipeline for user %s", user_id)
            else:
                logger.info("Pipeline already running for user %s — skipping", user_id)
    except Exception:
        logger.exception("Failed to trigger initial pipeline — user can wait for nightly run")

    return _response(200, {"status": "confirmed", "user_id": user_id})


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

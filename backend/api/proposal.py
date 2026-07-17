"""API handler: research proposal export.

POST /research/proposal
Body:
  {
    "mode": "bundle" | "full",
    "area_id": "<optional>"
  }
Returns:
  {
    "markdown": "<raw markdown>",
    "filename": "<slugged filename>.md",
    "papers_included": <int>,
    "generated_at": "<iso ts>"
  }

The client turns ``markdown`` into a Blob and triggers a download.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from backend.research.proposal_context import assemble_context
from backend.research.proposal_render import render_bundle_md, render_proposal_md
from backend.api._workspace_helper import get_user_id as _get_user_id, resolve_workspace_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        return super().default(o)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _slug(text: str) -> str:
    """Filesystem-safe slug from a workspace/area name."""
    text = (text or "workspace").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "workspace"


def handler(event: dict, context) -> dict:
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"ok": True})

    user_id = _get_user_id(event)
    if not user_id:
        return _response(401, {"error": "Unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return _response(400, {"error": "Invalid JSON body"})

    mode = (body.get("mode") or "bundle").lower()
    if mode not in ("bundle", "full"):
        return _response(400, {"error": "mode must be 'bundle' or 'full'"})
    area_id = (body.get("area_id") or "").strip() or None

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    workspace_id = resolve_workspace_id(table, event, user_id)
    if not workspace_id:
        return _response(400, {"error": "No active workspace. Create one first."})

    ctx = assemble_context(table, user_id, workspace_id, area_id=area_id)

    if mode == "bundle":
        markdown = render_bundle_md(ctx)
    else:
        markdown = render_proposal_md(ctx)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_stamp = generated_at[:10]
    slug_source = ctx.area_name or ctx.workspace_name
    mode_slug = "proposal" if mode == "full" else "context"
    filename = f"{_slug(slug_source)}-{mode_slug}-{date_stamp}.md"

    logger.info(
        "Proposal export: user=%s ws=%s mode=%s papers=%d filename=%s",
        user_id, workspace_id, mode, len(ctx.papers), filename,
    )

    return _response(200, {
        "markdown": markdown,
        "filename": filename,
        "papers_included": len(ctx.papers),
        "pinned_insights_included": len(ctx.pinned_insights),
        "generated_at": generated_at,
        "mode": mode,
    })

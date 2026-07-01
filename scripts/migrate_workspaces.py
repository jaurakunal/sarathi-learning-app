"""Workspaces migration script.

For each active user in SYSTEM#USERS, this script:
  1. Skips if the user already has any workspace (idempotent re-run).
  2. Generates a default workspace_id (KSUID).
  3. Splits the existing user-level profile META heuristically into:
        - User-level META  -> USER#<sub>#PROFILE SK=META
        - Workspace META   -> USER#<sub>#WS#<wid>#PROFILE SK=META
  4. Copies all workspace-scoped records from the legacy PK shape
     (USER#<sub>#X) into the new shape (USER#<sub>#WS#<wid>#X).
  5. Re-injects GSI keys (gsi1pk/gsi2pk/gsi4pk) so queries work in the new shape.
  6. Creates the workspace registry record (status=active, name="Default") and
     the active-workspace pointer.
  7. Sets the user-level onboarding marker so users don't have to re-onboard.

It does NOT delete legacy records — they remain as orphans (acceptable per the
task spec: "worst case ~3K orphan records, nobody reads them").

Usage:
  python -m scripts.migrate_workspaces             # dry run, prints plan
  python -m scripts.migrate_workspaces --apply     # actually writes to DDB
  python -m scripts.migrate_workspaces --user <sub>            # single user
  python -m scripts.migrate_workspaces --user <sub> --apply
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Iterable

import boto3
from boto3.dynamodb.conditions import Attr, Key

# Allow running both as a module (python -m) and as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.shared import db  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

USER_LEVEL_FIELDS = {
    "learning_style",
    "background",
    "math_comfort",
    "time_per_week",
    "paper_preference",
}
# Workspace-level META fields that we keep on the workspace's profile META.
# Anything not in USER_LEVEL_FIELDS that appears in the legacy meta gets copied
# under the workspace meta (e.g. paper_goal, hypothesis_brief, etc.).


def _new_workspace_id() -> str:
    """Generate a workspace_id (delegates to the API helper)."""
    from backend.api.workspaces import _new_workspace_id as gen
    return gen()


def _split_meta(legacy_meta: dict) -> tuple[dict, dict]:
    """Split a legacy profile META item into (user_level, workspace_level)."""
    if not legacy_meta:
        return {}, {}

    user_level: dict = {}
    workspace_level: dict = {}
    for k, v in legacy_meta.items():
        if k in {"PK", "SK", "user_id", "last_updated"}:
            continue
        if k in USER_LEVEL_FIELDS:
            user_level[k] = v
        else:
            workspace_level[k] = v
    return user_level, workspace_level


def _query_all(table, **kwargs) -> list[dict]:
    items: list[dict] = []
    resp = table.query(**kwargs)
    items.extend(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = table.query(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items.extend(resp.get("Items", []))
    return items


def _strip_keys(item: dict, keep_extra: Iterable[str] = ()) -> dict:
    """Remove DDB internal keys (PK/SK/gsi*) so we can re-write under new keys."""
    out = {}
    for k, v in item.items():
        if k in ("PK", "SK"):
            continue
        if k.startswith("gsi"):
            continue
        out[k] = v
    return out


def migrate_user(table, user_id: str, apply: bool) -> dict:
    """Migrate a single user. Returns a counts summary dict."""
    summary = {
        "user_id": user_id,
        "skipped": False,
        "workspace_id": None,
        "feed_cards": 0,
        "papers": 0,
        "engagement": 0,
        "profile_history": 0,
        "areas": 0,
        "summaries": 0,
        "conversations": 0,
        "turns": 0,
        "briefs": 0,
    }

    # Idempotency: skip if user already has any workspace.
    existing_ws = db.list_workspaces(table, user_id)
    if existing_ws:
        summary["skipped"] = True
        summary["workspace_id"] = existing_ws[0].get("workspace_id")
        logger.info("User %s already has %d workspaces — skipping", user_id, len(existing_ws))
        return summary

    workspace_id = _new_workspace_id()
    summary["workspace_id"] = workspace_id

    # 1. Read the legacy profile (PK=USER#<sub>#PROFILE)
    legacy_profile = _query_all(
        table,
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}#PROFILE"),
    )
    legacy_meta = next((it for it in legacy_profile if it.get("SK") == "META"), {})
    legacy_areas = [it for it in legacy_profile if (it.get("SK") or "").startswith("AREA#")]
    legacy_hypothesis = next((it for it in legacy_profile if it.get("SK") == "HYPOTHESIS"), None)
    legacy_summaries = [it for it in legacy_profile if (it.get("SK") or "").startswith("SUMMARY#")]

    user_level_meta, workspace_level_meta = _split_meta(legacy_meta)

    if apply:
        # 2. Write user-level META + onboarding marker
        if user_level_meta:
            db.put_user_meta(table, user_id, user_level_meta)
        db.set_user_onboarding_complete(table, user_id)

        # 3. Workspace meta
        if workspace_level_meta or legacy_meta:
            db.put_profile_meta(table, user_id, workspace_id, workspace_level_meta or {})

        # 4. Areas
        for a in legacy_areas:
            area = _strip_keys(a)
            db.put_profile_area(table, user_id, workspace_id, area)
            summary["areas"] += 1

        # 5. Hypothesis
        if legacy_hypothesis:
            db.put_profile_hypothesis(table, user_id, workspace_id, _strip_keys(legacy_hypothesis))

        # 6. Summaries
        for s in legacy_summaries:
            tier = s.get("tier", "")
            content = s.get("content", "")
            if tier:
                db.put_profile_summary(table, user_id, workspace_id, tier, content)
                summary["summaries"] += 1

        # 7. Profile history
        history = _query_all(
            table,
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}#PROFILE_HISTORY"),
        )
        for h in history:
            ev = _strip_keys(h)
            db.put_profile_history_event(table, user_id, workspace_id, ev)
            summary["profile_history"] += 1

        # 8. Feed cards
        cards = _query_all(
            table,
            KeyConditionExpression=(
                Key("PK").eq(f"USER#{user_id}#FEED")
                & Key("SK").begins_with("CARD#")
            ),
        )
        for card in cards:
            db.put_feed_card(table, user_id, workspace_id, _strip_keys(card))
            summary["feed_cards"] += 1

        # 9. Papers (via GSI2 — list each status partition)
        for status in ("candidate", "triaged", "surfaced", "digested", "rejected", "skipped"):
            papers = _query_all(
                table,
                IndexName="GSI2",
                KeyConditionExpression=Key("gsi2pk").eq(f"USER#{user_id}#PAPER_STATUS#{status}"),
            )
            for p in papers:
                db.put_paper(table, user_id, workspace_id, _strip_keys(p))
                summary["papers"] += 1

        # 10. Engagement events
        engagement = _query_all(
            table,
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}#ENGAGEMENT"),
        )
        for e in engagement:
            ev = _strip_keys(e)
            db.put_engagement_event(table, user_id, workspace_id, ev)
            summary["engagement"] += 1

        # 11. Briefs
        briefs = _query_all(
            table,
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}#BRIEF"),
        )
        for b in briefs:
            new_pk = db._brief_pk(user_id, workspace_id)
            new_item = {**_strip_keys(b), "PK": new_pk, "SK": b.get("SK", ""), "workspace_id": workspace_id}
            table.put_item(Item=new_item)
            summary["briefs"] += 1

        # 12. Conversations + turns (via GSI1)
        convs = _query_all(
            table,
            IndexName="GSI1",
            KeyConditionExpression=(
                Key("gsi1pk").eq(f"USER#{user_id}")
                & Key("gsi1sk").begins_with("CONV#")
            ),
        )
        for conv_meta in convs:
            conv_id = conv_meta.get("conv_id", "")
            if not conv_id:
                continue
            old_pk = f"USER#{user_id}#CONV#{conv_id}"
            new_pk = db._conv_pk(user_id, workspace_id, conv_id)
            items = _query_all(
                table,
                KeyConditionExpression=Key("PK").eq(old_pk),
            )
            for it in items:
                base = _strip_keys(it)
                base["PK"] = new_pk
                base["SK"] = it["SK"]
                if it["SK"] == "META":
                    base["gsi1pk"] = db._gsi_user_scope(user_id, workspace_id)
                    base["gsi1sk"] = f"CONV#{conv_id}"
                table.put_item(Item=base)
                if it["SK"] == "META":
                    summary["conversations"] += 1
                elif it["SK"].startswith("TURN#"):
                    summary["turns"] += 1

        # 13. Pipeline run
        legacy_pipeline = table.get_item(
            Key={"PK": f"USER#{user_id}#PIPELINE", "SK": "LATEST"},
        ).get("Item")
        if legacy_pipeline:
            new_pipeline = _strip_keys(legacy_pipeline)
            new_pipeline["PK"] = db._pipeline_pk(user_id, workspace_id)
            new_pipeline["SK"] = "LATEST"
            new_pipeline["workspace_id"] = workspace_id
            table.put_item(Item=new_pipeline)

        # 14. Create workspace registry record + active pointer
        db.create_workspace(table, user_id, workspace_id, name="Default")
        db.set_active_workspace(table, user_id, workspace_id)

    logger.info("User %s -> workspace %s; counts=%s", user_id, workspace_id, summary)
    return summary


def list_active_users(table) -> list[str]:
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq("SYSTEM#USERS") & Key("SK").begins_with("USER#")
        ),
    )
    return [u.get("user_id", "") for u in resp.get("Items", []) if u.get("user_id")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate users to workspaces.")
    parser.add_argument("--table", default=os.environ.get("TABLE_NAME", "sarathi"))
    parser.add_argument("--user", help="Migrate only this user_id")
    parser.add_argument("--apply", action="store_true", help="Actually write to DDB")
    args = parser.parse_args()

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(args.table)

    if args.user:
        users = [args.user]
    else:
        users = list_active_users(table)

    logger.info("Migrating %d users (apply=%s)", len(users), args.apply)
    summaries = []
    for uid in users:
        summaries.append(migrate_user(table, uid, args.apply))

    skipped = sum(1 for s in summaries if s["skipped"])
    migrated = len(summaries) - skipped
    logger.info("Done. migrated=%d skipped=%d", migrated, skipped)
    for s in summaries:
        logger.info("  %s", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())

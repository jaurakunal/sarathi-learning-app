"""Eval dataset construction.

The "golden dataset" is the live user's real digested papers + the engagement
they earned (read, dismissed, bookmarked, rated, tagged, pinned chat insights).
We persist it under EVAL#DATASET so re-running setup is idempotent and downstream
runs / judges can reference a stable snapshot.

In addition to the positive class (digested papers), we maintain a NEGATIVE
class — real papers Sonnet rejected at triage — under EVAL#DATASET_NEG. This
gives evals a real specificity signal: a candidate model that's too lenient
(everything = "worth your time") fails on negatives. Sonnet's stored decision
fields (worth_my_hours, triage_score, triage_level, triage_reasoning,
hypothesis_relevant) are preserved as the golden answer.

Single-table layout (extends the patterns in backend.shared.db):
  PK=EVAL#DATASET                  SK=PAPER#<paper_id>     paper + golden card + engagement (positive)
  PK=EVAL#DATASET                  SK=META                 dataset metadata
  PK=EVAL#DATASET_NEG              SK=PAPER#<paper_id>     rejected paper + Sonnet golden decision
  PK=EVAL#DATASET_NEG              SK=META                 negative dataset metadata
  PK=EVAL#RUN#<run_id>             SK=META                 run summary
  PK=EVAL#RUN#<run_id>             SK=PAPER#<paper_id>     candidate card + cost/timing
  PK=EVAL#JUDGE#<judge_run_id>     SK=META                 judge run summary
  PK=EVAL#JUDGE#<judge_run_id>     SK=PAPER#<paper_id>     per-paper judge scores
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from boto3.dynamodb.conditions import Key

from backend.shared import db

logger = logging.getLogger(__name__)

# Public constants — also referenced by runner / judge / scripts
LIVE_USER_ID = "00000000-0000-0000-0000-000000000000"
TEST_USER_ID = "447844a8-c0e1-700b-2fdf-f9512eee3e49"
TEST_USER_EMAIL = "kunal@example.com"

DATASET_PK = "EVAL#DATASET"
DATASET_NEG_PK = "EVAL#DATASET_NEG"


# ---------------------------------------------------------------------------
# Profile cloning (live → test). Read-only on live; write on test.
# ---------------------------------------------------------------------------


def clone_profile(table, source_user_id: str = LIVE_USER_ID,
                  target_user_id: str = TEST_USER_ID) -> dict:
    """Copy the META + AREA + HYPOTHESIS records from live to test user.

    SUMMARY tiers are intentionally skipped — the digest step doesn't need them
    to be deterministic and they bloat the prompt.

    Returns a summary dict {meta_copied, areas_copied, hypothesis_copied}.
    """
    profile = db.get_full_profile(table, source_user_id)
    summary = {"meta_copied": 0, "areas_copied": 0, "hypothesis_copied": 0}

    meta = profile.get("meta")
    if meta:
        meta_clean = {
            k: v for k, v in meta.items()
            if k not in ("PK", "SK", "user_id", "last_updated")
        }
        db.put_profile_meta(table, target_user_id, meta_clean)
        summary["meta_copied"] = 1

    for area in profile.get("areas", []) or []:
        area_clean = {
            k: v for k, v in area.items()
            if k not in ("PK", "SK", "user_id")
        }
        if "id" not in area_clean:
            continue
        db.put_profile_area(table, target_user_id, area_clean)
        summary["areas_copied"] += 1

    hyp = profile.get("hypothesis")
    if hyp:
        hyp_clean = {
            k: v for k, v in hyp.items()
            if k not in ("PK", "SK", "user_id")
        }
        db.put_profile_hypothesis(table, target_user_id, hyp_clean)
        summary["hypothesis_copied"] = 1

    logger.info("Cloned profile %s → %s: %s", source_user_id, target_user_id, summary)
    return summary


# ---------------------------------------------------------------------------
# Engagement aggregation per paper
# ---------------------------------------------------------------------------


def get_engagement_for_paper(table, user_id: str, paper_id: str) -> dict:
    """Aggregate all engagement events for a paper into a compact summary.

    Uses GSI4 (PAPER_ENGAGEMENT) — see db.py docstring.
    Returns a dict with booleans + counts: read, dismissed, bookmarked,
    rated_value, tagged, pinned_count, time_on_page_ms, raw_events.
    """
    resp = table.query(
        IndexName="GSI4",
        KeyConditionExpression=Key("gsi4pk").eq(
            f"USER#{user_id}#PAPER_ENGAGEMENT#{paper_id}"
        ),
    )
    events = resp.get("Items", [])

    summary: dict[str, Any] = {
        "read": False,
        "dismissed": False,
        "bookmarked": False,
        "rated_value": None,
        "tagged": [],
        "pinned_count": 0,
        "time_on_page_ms": 0,
        "viewed": False,
        "source_clicked": False,
        "raw_events": [],
    }

    for ev in events:
        action = ev.get("action", "")
        summary["raw_events"].append({
            "action": action,
            "ts": ev.get("ts", ""),
            "value": ev.get("value"),
        })
        if action == "read":
            summary["read"] = True
        elif action == "dismiss":
            summary["dismissed"] = True
        elif action == "bookmark":
            summary["bookmarked"] = True
        elif action == "rate":
            summary["rated_value"] = ev.get("value")
        elif action == "tag":
            tags = ev.get("tags") or []
            if isinstance(tags, list):
                summary["tagged"].extend(tags)
        elif action == "pin":
            summary["pinned_count"] += 1
        elif action == "view":
            summary["viewed"] = True
        elif action == "source_click":
            summary["source_clicked"] = True
        elif action == "time_on_page":
            try:
                summary["time_on_page_ms"] += int(ev.get("value") or 0)
            except (TypeError, ValueError):
                pass

    return summary


def get_pinned_chat_insights(table, user_id: str, paper_id: str) -> list[dict]:
    """Return all pinned conversation turns for a paper (paper-scoped conv_id == paper_id)."""
    try:
        turns = db.get_pinned_turns(table, user_id, paper_id)
    except Exception:
        return []
    insights = []
    for t in turns:
        insights.append({
            "seq": t.get("seq"),
            "request": t.get("request", ""),
            "response": t.get("response", ""),
            "pin_note": t.get("pin_note", ""),
        })
    return insights


# ---------------------------------------------------------------------------
# Build / persist the eval dataset
# ---------------------------------------------------------------------------


def list_digested_papers(table, user_id: str, limit: int = 200) -> list[dict]:
    """Pull all digested papers from GSI2."""
    return db.list_papers_by_status(table, user_id, "digested", limit=limit)


def build_dataset_entries(table, source_user_id: str = LIVE_USER_ID,
                          limit: int = 200) -> list[dict]:
    """Read live user's digested papers + match each to its golden card + engagement.

    Returns a list of dicts ready to write under EVAL#DATASET.
    """
    papers = list_digested_papers(table, source_user_id, limit=limit)
    entries: list[dict] = []

    for paper in papers:
        paper_id = paper.get("id")
        if not paper_id:
            continue

        golden_card = db.get_feed_card_by_paper(table, source_user_id, paper_id)
        engagement = get_engagement_for_paper(table, source_user_id, paper_id)
        pinned = get_pinned_chat_insights(table, source_user_id, paper_id)

        # Strip DDB internal keys from card so it round-trips cleanly
        golden_card_clean: Optional[dict] = None
        if golden_card:
            golden_card_clean = {
                k: v for k, v in golden_card.items()
                if k not in ("PK", "SK")
            }

        # Strip DDB internal keys from paper too
        paper_clean = {
            k: v for k, v in paper.items()
            if k not in ("PK", "SK", "gsi2pk", "gsi2sk")
        }

        entries.append({
            "paper_id": paper_id,
            "paper": paper_clean,
            "golden_card": golden_card_clean,
            "engagement": engagement,
            "pinned_insights": pinned,
        })

    logger.info("Built %d dataset entries from live user", len(entries))
    return entries


def persist_dataset(table, entries: Iterable[dict]) -> int:
    """Write the eval dataset under EVAL#DATASET (idempotent — overwrites).

    Returns the number of entries written.
    """
    count = 0
    for entry in entries:
        paper_id = entry.get("paper_id")
        if not paper_id:
            continue
        item = {
            "PK": DATASET_PK,
            "SK": f"PAPER#{paper_id}",
            **entry,
        }
        table.put_item(Item=db._sanitize_item(item))
        count += 1

    # Write the META item so report/judge can show how many papers were captured
    meta = {
        "PK": DATASET_PK,
        "SK": "META",
        "paper_count": count,
        "last_built": db._now_iso(),
        "source_user_id": LIVE_USER_ID,
    }
    table.put_item(Item=db._sanitize_item(meta))
    logger.info("Persisted eval dataset: %d papers", count)
    return count


def load_dataset(table) -> list[dict]:
    """Load all dataset entries from DDB."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(DATASET_PK) & Key("SK").begins_with("PAPER#")
        ),
    )
    items = resp.get("Items", [])
    entries = []
    for item in items:
        entry = {k: v for k, v in item.items() if k not in ("PK", "SK")}
        entries.append(entry)
    while resp.get("LastEvaluatedKey"):
        resp = table.query(
            KeyConditionExpression=(
                Key("PK").eq(DATASET_PK) & Key("SK").begins_with("PAPER#")
            ),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        for item in resp.get("Items", []):
            entry = {k: v for k, v in item.items() if k not in ("PK", "SK")}
            entries.append(entry)
    return entries


def get_dataset_meta(table) -> Optional[dict]:
    """Get the dataset META item if present."""
    resp = table.get_item(Key={"PK": DATASET_PK, "SK": "META"})
    return resp.get("Item")


# ---------------------------------------------------------------------------
# Negative-class dataset (rejected-at-triage papers)
# ---------------------------------------------------------------------------


def list_candidate_papers(table, user_id: str, limit: int = 500) -> list[dict]:
    """Pull papers in `candidate` status — these are papers that were triaged
    but did NOT progress to digest (Sonnet rejected them).
    """
    return db.list_papers_by_status(table, user_id, "candidate", limit=limit)


def _has_triage_decision(paper: dict) -> bool:
    """A candidate paper is useful as a negative example only if Sonnet
    actually scored it (some candidates may be in flight or partial)."""
    return (
        paper.get("worth_my_hours") is not None
        and paper.get("triage_score") is not None
    )


def _sample_diverse_candidates(papers: list[dict], limit: int) -> list[dict]:
    """Round-robin sample papers across (level, hypothesis_relevant) buckets so
    the negative set isn't dominated by one rejection mode (e.g., all over_head).

    Buckets: over_head / too_basic / just_right (with worth_my_hours=False),
    cross-cut by hypothesis_relevant True/False. We interleave from each
    non-empty bucket until we hit `limit` to keep the mix diverse.
    """
    buckets: dict[tuple[str, bool], list[dict]] = {}
    for p in papers:
        if not _has_triage_decision(p):
            continue
        # Only keep "rejected by Sonnet" papers as negatives — worth_my_hours
        # must be False. Some candidates might have True but be stuck in
        # candidate state for other reasons; we exclude those to keep the
        # negative class semantically clean.
        if p.get("worth_my_hours") is True:
            continue
        level = p.get("triage_level") or "unknown"
        hyp = bool(p.get("hypothesis_relevant"))
        buckets.setdefault((level, hyp), []).append(p)

    # Stable order so re-running with the same data picks the same items
    for k in buckets:
        buckets[k].sort(key=lambda x: x.get("id", ""))

    out: list[dict] = []
    bucket_keys = sorted(buckets.keys())
    idx = {k: 0 for k in bucket_keys}
    while len(out) < limit:
        progressed = False
        for k in bucket_keys:
            if len(out) >= limit:
                break
            i = idx[k]
            if i < len(buckets[k]):
                out.append(buckets[k][i])
                idx[k] = i + 1
                progressed = True
        if not progressed:
            break
    return out


def build_negative_dataset_entries(
    table, source_user_id: str = LIVE_USER_ID, limit: int = 50,
) -> list[dict]:
    """Pull papers Sonnet rejected at triage as negative-class eval examples.

    Each entry shape mirrors `build_dataset_entries` so positive + negative
    paths can share aggregation code:
      {
        "paper_id": ...,
        "paper": <full paper dict, with Sonnet decision fields preserved>,
        "golden_card": None,        # negatives have no card
        "engagement": {...empty},
        "pinned_insights": [],
        "is_negative": True,
      }
    """
    raw = list_candidate_papers(table, source_user_id, limit=max(limit * 5, 200))
    sampled = _sample_diverse_candidates(raw, limit=limit)
    entries: list[dict] = []

    for paper in sampled:
        paper_id = paper.get("id")
        if not paper_id:
            continue
        paper_clean = {
            k: v for k, v in paper.items()
            if k not in ("PK", "SK", "gsi2pk", "gsi2sk")
        }
        entries.append({
            "paper_id": paper_id,
            "paper": paper_clean,
            "golden_card": None,
            "engagement": {
                "read": False,
                "dismissed": False,
                "bookmarked": False,
                "rated_value": None,
                "tagged": [],
                "pinned_count": 0,
                "time_on_page_ms": 0,
                "viewed": False,
                "source_clicked": False,
                "raw_events": [],
            },
            "pinned_insights": [],
            "is_negative": True,
        })

    logger.info(
        "Built %d negative dataset entries (from %d raw candidates)",
        len(entries), len(raw),
    )
    return entries


def persist_negative_dataset(table, entries: Iterable[dict]) -> int:
    """Write the negative eval dataset under EVAL#DATASET_NEG (idempotent —
    overwrites). Returns the number of entries written.
    """
    count = 0
    for entry in entries:
        paper_id = entry.get("paper_id")
        if not paper_id:
            continue
        # Force is_negative flag in case caller forgot
        item = {
            "PK": DATASET_NEG_PK,
            "SK": f"PAPER#{paper_id}",
            **entry,
            "is_negative": True,
        }
        table.put_item(Item=db._sanitize_item(item))
        count += 1

    meta = {
        "PK": DATASET_NEG_PK,
        "SK": "META",
        "paper_count": count,
        "last_built": db._now_iso(),
        "source_user_id": LIVE_USER_ID,
    }
    table.put_item(Item=db._sanitize_item(meta))
    logger.info("Persisted negative eval dataset: %d papers", count)
    return count


def load_negative_dataset(table) -> list[dict]:
    """Load all negative dataset entries from DDB."""
    resp = table.query(
        KeyConditionExpression=(
            Key("PK").eq(DATASET_NEG_PK) & Key("SK").begins_with("PAPER#")
        ),
    )
    items = resp.get("Items", [])
    entries = []
    for item in items:
        entry = {k: v for k, v in item.items() if k not in ("PK", "SK")}
        entries.append(entry)
    while resp.get("LastEvaluatedKey"):
        resp = table.query(
            KeyConditionExpression=(
                Key("PK").eq(DATASET_NEG_PK) & Key("SK").begins_with("PAPER#")
            ),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        for item in resp.get("Items", []):
            entry = {k: v for k, v in item.items() if k not in ("PK", "SK")}
            entries.append(entry)
    return entries


def get_negative_dataset_meta(table) -> Optional[dict]:
    """Get the negative dataset META item if present."""
    resp = table.get_item(Key={"PK": DATASET_NEG_PK, "SK": "META"})
    return resp.get("Item")


def load_combined_dataset(table) -> list[dict]:
    """Load positive (is_negative=False) + negative (is_negative=True) entries.

    Positives are tagged with `is_negative=False` so downstream metric code
    can split classes cleanly.
    """
    positives = load_dataset(table)
    for e in positives:
        e.setdefault("is_negative", False)
    negatives = load_negative_dataset(table)
    for e in negatives:
        e["is_negative"] = True
    return positives + negatives

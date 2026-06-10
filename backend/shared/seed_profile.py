"""Seed a user profile into DynamoDB from the onboarding interview data.

Usage:
    python -m backend.shared.seed_profile <user_id> <table_name>

Writes all profile items (META, 4 AREA items, HYPOTHESIS, 5 SUMMARY tiers)
plus profile_history events (area_added x4, hypothesis_added x1).
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from datetime import datetime, timezone

import boto3

from backend.shared.models import (
    Area,
    AreaRole,
    AreaStatus,
    Hypothesis,
    LearningStyle,
    ProfileHistoryEvent,
    ProfileMeta,
    ReadingSpeed,
)

NOW = "2026-06-10T00:00:00Z"


def _pk(user_id: str) -> str:
    return f"USER#{user_id}#PROFILE"


def _history_pk(user_id: str) -> str:
    return f"USER#{user_id}#PROFILE_HISTORY"


def build_meta(user_id: str) -> dict:
    """Build the META item."""
    meta = ProfileMeta(
        user_id=user_id,
        learning_style=LearningStyle(
            math="route-around; tap-to-reveal only; never gate",
            lead_with="applied / can-I-use-this",
            tone="sharp mirror, no flattery, credit at exact scope",
        ),
        reading_speed=ReadingSpeed(
            initial_idle_threshold_s=60,
            current_idle_threshold_s=60,
            avg_active_ms_per_card=None,
            confidence="low",
            last_calibrated=None,
        ),
        paper_goal="Accumulate citations/claims/gaps toward my own paper.",
        last_updated=NOW,
    )
    item = asdict(meta)
    item["PK"] = _pk(user_id)
    item["SK"] = "META"
    return item


def build_areas(user_id: str) -> list[dict]:
    """Build all AREA# items."""
    areas = [
        Area(
            id="person-clone-personality",
            user_id=user_id,
            label="Person-cloning / mental models",
            status=AreaStatus.ACTIVE,
            role=AreaRole.SPINE,
            links=["agent-memory", "contemplative-memory"],
            frontier=(
                "Built a cloning prototype cold; hasn't read Generative Agents; "
                "doesn't know 'reflection' formally."
            ),
            too_basic=["intro to RAG", "what are agents"],
            just_right=["memory architectures", "agent personas"],
            added_at=NOW,
        ),
        Area(
            id="agent-memory",
            user_id=user_id,
            label="Human + Eastern memory models → agentic brain",
            status=AreaStatus.ACTIVE,
            role=AreaRole.SPINE,
            links=["person-clone-personality", "contemplative-memory"],
            frontier=(
                "Interested in clarity-of-mind as architecture; hasn't read "
                "formal memory consolidation literature."
            ),
            too_basic=["what is a vector database"],
            just_right=[
                "memory stream architectures",
                "reflection mechanisms",
                "salience/forgetting models",
            ],
            added_at=NOW,
        ),
        Area(
            id="long-running-agents",
            user_id=user_id,
            label="Long-running agentic flows",
            status=AreaStatus.ACTIVE,
            role=AreaRole.SECONDARY,
            links=["person-clone-personality"],
            frontier=(
                "Wants to run agents autonomously (online store, social presence); "
                "no formal reading on agent longevity."
            ),
            too_basic=["intro to AI agents"],
            just_right=[
                "agent persistence",
                "state management over time",
                "autonomous multi-step flows",
            ],
            added_at=NOW,
        ),
        Area(
            id="adversarial-security",
            user_id=user_id,
            label="Adversarial/security agents (red vs blue)",
            status=AreaStatus.ACTIVE,
            role=AreaRole.SECONDARY,
            links=[],
            frontier=(
                "Built a security audit tool for vibe coders using LLMs; "
                "interested in Anthropic's AI-as-attack-agent work."
            ),
            too_basic=["what is a pentest"],
            just_right=[
                "LLM-driven attack simulation",
                "adversarial agent architectures",
                "red-team automation",
            ],
            added_at=NOW,
        ),
    ]

    items = []
    for area in areas:
        item = asdict(area)
        # Serialize enum values to their string form
        item["status"] = area.status.value
        item["role"] = area.role.value
        item["PK"] = _pk(user_id)
        item["SK"] = f"AREA#{area.id}"
        items.append(item)
    return items


def build_hypothesis(user_id: str) -> dict:
    """Build the HYPOTHESIS item."""
    hyp = Hypothesis(
        user_id=user_id,
        statement="Brain-structure + agentic harness >> the LLM.",
        status="untested",
        supporting=[],
        refuting=[],
        refining=[],
    )
    item = asdict(hyp)
    item["PK"] = _pk(user_id)
    item["SK"] = "HYPOTHESIS"
    return item


def build_summaries(user_id: str) -> list[dict]:
    """Build all SUMMARY# items (one per tier)."""
    tiers = ["yesterday", "3_day", "7_day", "month", "quarter"]
    items = []
    for tier in tiers:
        items.append(
            {
                "PK": _pk(user_id),
                "SK": f"SUMMARY#{tier}",
                "user_id": user_id,
                "tier": tier,
                "content": "No activity yet.",
                "last_updated": NOW,
            }
        )
    return items


def build_history_events(user_id: str) -> list[dict]:
    """Build profile_history events for the initial seeding."""
    area_ids = [
        "person-clone-personality",
        "agent-memory",
        "long-running-agents",
        "adversarial-security",
    ]
    events: list[dict] = []

    for i, area_id in enumerate(area_ids):
        # Offset each event by 1 second so SKs are unique
        ts = f"2026-06-10T00:00:0{i}Z"
        evt = ProfileHistoryEvent(
            user_id=user_id,
            ts=ts,
            type="area_added",
            area_id=area_id,
            reason="onboarding interview",
        )
        item = asdict(evt)
        item["PK"] = _history_pk(user_id)
        item["SK"] = f"EVENT#{ts}"
        events.append(item)

    # hypothesis_added event
    hyp_ts = "2026-06-10T00:00:04Z"
    hyp_evt = ProfileHistoryEvent(
        user_id=user_id,
        ts=hyp_ts,
        type="hypothesis_added",
        reason="onboarding interview",
    )
    hyp_item = asdict(hyp_evt)
    hyp_item["PK"] = _history_pk(user_id)
    hyp_item["SK"] = f"EVENT#{hyp_ts}"
    events.append(hyp_item)

    return events


def seed_profile(user_id: str, table_name: str) -> None:
    """Write all profile items and history events to DynamoDB."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # Collect all items to write
    items: list[dict] = []
    items.append(build_meta(user_id))
    items.extend(build_areas(user_id))
    items.append(build_hypothesis(user_id))
    items.extend(build_summaries(user_id))
    items.extend(build_history_events(user_id))

    # Write in batches of 25 (DDB batch_write limit)
    with table.batch_writer() as batch:
        for item in items:
            # Remove None values — DDB doesn't accept them
            cleaned = {k: v for k, v in item.items() if v is not None}
            batch.put_item(Item=cleaned)

    print(f"Seeded {len(items)} items for user {user_id} in table {table_name}")
    print(f"  - 1 META item")
    print(f"  - 4 AREA items")
    print(f"  - 1 HYPOTHESIS item")
    print(f"  - 5 SUMMARY items")
    print(f"  - 5 profile_history events (4 area_added + 1 hypothesis_added)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m backend.shared.seed_profile <user_id> <table_name>")
        sys.exit(1)

    user_id = sys.argv[1]
    table_name = sys.argv[2]
    seed_profile(user_id, table_name)

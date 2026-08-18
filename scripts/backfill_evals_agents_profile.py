"""One-off backfill: port kunaljaura@gmail.com's onboarding profile into the
"Evals+Agents" workspace and trigger its first pipeline run.

Context: the 2026-08-18 onboarding conversation was misrouted into the Default
workspace and its completion JSON never parsed, so "Evals+Agents" ended up
empty. The user's answers are recovered from that conversation (TURN#00014)
and written here with humanized labels. Mirrors _confirm_workspace_profile in
backend/api/onboarding_confirm.py.

Usage:
  AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python -m scripts.backfill_evals_agents_profile          # dry run
  AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python -m scripts.backfill_evals_agents_profile --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.shared import db  # noqa: E402

USER_ID = "00000000-0000-0000-0000-000000000000"
WORKSPACE_ID = "1711a0f6c400ba9063d31945335981cf9db0b573"  # Evals+Agents
TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")
STATE_MACHINE_ARN = os.environ.get(
    "STATE_MACHINE_ARN",
    "arn:aws:states:us-east-1:123456789012:stateMachine:sarathi-nightly-pipeline",
)
BUCKET_NAME = os.environ.get("BUCKET_NAME", "sarathi-123456789012-us-east-1")

# Recovered + humanized from the Default-workspace onboarding TURN#00014 JSON.
PROFILE = {
    "meta": {
        "paper_goal": (
            "Consume work on agentic evaluation; produce work on long-horizon "
            "agent memory and task persistence."
        ),
        "workspace_summary": (
            "An engineer transitioning to researcher, building an agent harness "
            "in Rust. Focused on making long-running agents reliable and on how "
            "to evaluate agent trajectories."
        ),
    },
    "areas": [
        {
            "id": "long-running-agent-reliability",
            "label": "Long-running agent reliability",
            "role": "primary",
            "just_right": [
                "task persistence across long horizons",
                "todo and memory modules for agents",
                "recursive self-refinement",
                "MemGPT-style persistent memory",
            ],
            "too_basic": ["chain of thought", "ReAct"],
        },
        {
            "id": "agentic-evaluation",
            "label": "Agentic evaluation",
            "role": "primary",
            "just_right": [
                "trajectory evaluation",
                "AgentBench",
                "GAIA",
                "LLM-as-judge beyond basic prompting",
            ],
            "too_basic": ["what is an eval", "basic LLM-as-judge prompting"],
        },
    ],
    "hypothesis": {
        "statement": (
            "Persistent memory plus a disciplined harness (with an explicit todo "
            "list and a memory module) improves long-horizon agent faithfulness."
        ),
        "status": "forming",
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    existing = db.get_full_profile(table, USER_ID, WORKSPACE_ID)
    if existing.get("areas"):
        print("Workspace already has profile areas — aborting to avoid clobber.")
        print(json.dumps({"areas": len(existing["areas"])}, indent=2))
        return 1

    print(f"Target: user={USER_ID} ws={WORKSPACE_ID} (Evals+Agents)")
    print(json.dumps(PROFILE, indent=2))

    if not args.apply:
        print("\nDRY RUN — pass --apply to write + trigger pipeline.")
        return 0

    # 1. Profile meta
    db.put_profile_meta(table, USER_ID, WORKSPACE_ID, PROFILE["meta"])
    # 2. Areas
    for area in PROFILE["areas"]:
        db.put_profile_area(table, USER_ID, WORKSPACE_ID, area)
    # 3. Hypothesis
    db.put_profile_hypothesis(table, USER_ID, WORKSPACE_ID, PROFILE["hypothesis"])
    print("Profile written.")

    # 4. Trigger the pipeline (mirrors onboarding_confirm.py)
    sfn = boto3.client("stepfunctions")
    resp = sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        input=json.dumps({
            "user_id": USER_ID,
            "workspace_id": WORKSPACE_ID,
            "table_name": TABLE_NAME,
            "s3_bucket": BUCKET_NAME,
            "since_days": 30,
        }),
    )
    execution_arn = resp.get("executionArn", "")
    db.put_pipeline_run(table, USER_ID, WORKSPACE_ID, execution_arn, "running")
    print(f"Pipeline triggered: {execution_arn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

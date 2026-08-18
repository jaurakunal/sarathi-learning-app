"""One-off: copy the misrouted onboarding conversation turns from the Default
workspace into the Evals+Agents workspace, where they belong.

The 2026-08-18 onboarding for kunaljaura@gmail.com was misrouted: turns 2-16
landed in Default's onboarding thread. Default's TURN#00001 is the older
("Hi, I just signed up") user-level opener and is NOT part of this
conversation, so it is skipped. Evals+Agents keeps its own TURN#00001 opener
("What's this workspace for?") and receives turns 2-16 after it.

Copy-don't-move: the Default turns are left in place (deletion is a separate,
explicit step if wanted).

Usage:
  AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python -m scripts.copy_onboarding_convo_to_evals_agents
  AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python -m scripts.copy_onboarding_convo_to_evals_agents --apply
"""

from __future__ import annotations

import argparse
import os
import sys

import boto3
from boto3.dynamodb.conditions import Key

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

USER_ID = "00000000-0000-0000-0000-000000000000"
SRC_WS = "agprwrwy2czsjcvvvw66i6bsjz7"          # Default
DST_WS = "1711a0f6c400ba9063d31945335981cf9db0b573"  # Evals+Agents
TABLE_NAME = os.environ.get("TABLE_NAME", "sarathi")

SRC_PK = f"USER#{USER_ID}#WS#{SRC_WS}#CONV#onboarding"
DST_PK = f"USER#{USER_ID}#WS#{DST_WS}#CONV#onboarding"


def _query_all(table, pk: str) -> list[dict]:
    items, resp = [], table.query(KeyConditionExpression=Key("PK").eq(pk))
    items.extend(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = table.query(KeyConditionExpression=Key("PK").eq(pk), ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    src = _query_all(table, SRC_PK)
    src_turns = sorted(
        [i for i in src if i.get("SK", "").startswith("TURN#")],
        key=lambda i: i.get("SK", ""),
    )
    # Skip TURN#00001 (the old user-level "Hi, I just signed up" opener).
    to_copy = [t for t in src_turns if t.get("SK") != "TURN#00001"]

    dst = _query_all(table, DST_PK)
    dst_turns = [i for i in dst if i.get("SK", "").startswith("TURN#")]

    print(f"Source (Default): {len(src_turns)} turns, copying {len(to_copy)} (skipping TURN#00001)")
    print(f"Dest (Evals+Agents): currently {len(dst_turns)} turns")
    for t in to_copy:
        print(f"  {t.get('SK')}  {str(t.get('request',''))[:70]!r}")

    if len(dst_turns) > 1:
        print("\nDest already has more than the opener turn — aborting to avoid duplicates.")
        return 1

    if not args.apply:
        print("\nDRY RUN — pass --apply to copy.")
        return 0

    max_seq = 1  # dest opener is TURN#00001
    with table.batch_writer() as batch:
        for t in to_copy:
            new = dict(t)
            new["PK"] = DST_PK           # keep same SK / seq / timestamps / content
            batch.put_item(Item=new)
            # seq comes back from DDB as a Decimal; derive from the SK to be safe.
            sk = new.get("SK", "")
            if sk.startswith("TURN#"):
                try:
                    max_seq = max(max_seq, int(sk.split("#", 1)[1]))
                except ValueError:
                    pass
    print(f"Copied {len(to_copy)} turns into Evals+Agents.")

    # Bump the dest conversation META turn_count.
    table.update_item(
        Key={"PK": DST_PK, "SK": "META"},
        UpdateExpression="SET turn_count = :n",
        ExpressionAttributeValues={":n": max_seq},
    )
    print(f"Updated dest conv META turn_count -> {max_seq}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

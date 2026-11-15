"""Run the pipeline locally against real AWS (DDB + Bedrock).

Usage:
    source .venv/bin/activate
    AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python scripts/test_local_pipeline.py [step]

Steps: discover, triage, select, digest, lens, connect, all (default: discover)
"""

import json
import logging
import sys
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Ensure backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVENT = {
    "user_id": "00000000-0000-0000-0000-000000000000",
    "table_name": "sarathi",
    "s3_bucket": "sarathi-123456789012-us-east-1",
}


def run_discover():
    from backend.pipeline.discover import handler
    result = handler(EVENT, None)
    print(json.dumps(result, indent=2))
    return result


def run_triage():
    from backend.pipeline.triage import handler
    result = handler(EVENT, None)
    print(json.dumps(result, indent=2))
    return result


def run_select():
    from backend.pipeline.select import handler
    result = handler(EVENT, None)
    print(json.dumps(result, indent=2))
    return result


def run_digest():
    from backend.pipeline.digest import run
    result = run(EVENT)
    print(json.dumps(result, indent=2))
    return result


def run_lens():
    from backend.pipeline.lens import handler
    result = handler(EVENT, None)
    print(json.dumps(result, indent=2))
    return result


def run_connect():
    from backend.pipeline.connect import handler
    result = handler(EVENT, None)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "discover"

    steps = {
        "discover": run_discover,
        "triage": run_triage,
        "select": run_select,
        "digest": run_digest,
        "lens": run_lens,
        "connect": run_connect,
    }

    if step == "all":
        for name, fn in steps.items():
            print(f"\n{'='*60}\n  STEP: {name}\n{'='*60}")
            fn()
    elif step in steps:
        steps[step]()
    else:
        print(f"Unknown step: {step}. Options: {', '.join(steps.keys())}, all")
        sys.exit(1)

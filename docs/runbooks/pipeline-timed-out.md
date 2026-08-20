---
alarm_name: sarathi-pipeline-timed-out
severity: sev3
metric: AWS/States/ExecutionsTimedOut (sarathi-nightly-pipeline)
auto_fixable: partial
auto_remediation: B
auto_remediation_note: >
  Tier B. A timeout is a slow-dependency / volume signal (Bedrock latency,
  DynamoDB backoff, legitimate fanout growth), not a deterministic code bug, so
  the agent runs diagnostics and REPORTS findings only. The one code candidate
  here (`unbounded-query`) is confidence:low, so it never clears the A gate;
  surface it as a proposal for a human, do not implement it.
owning_component: nightly-pipeline
related_alarms:
  - sarathi-pipeline-failed
  - sarathi-feed-stale
  - sarathi-llm-failures
  - sarathi-ddb-throttled
schema_version: 1
---

# sarathi-pipeline-timed-out

A `sarathi-nightly-pipeline` execution hit the 2h state-machine timeout. The
work did not fail, it stopped making progress fast enough. This usually means a
step is blocked on a slow dependency rather than throwing.

## Symptoms

- `ExecutionsTimedOut >= 1` for `sarathi-nightly-pipeline`.
- The execution history ends with a state still RUNNING at the timeout, not a
  `TaskFailed`.
- Often co-fires `sarathi-feed-stale` (timed-out workspace produced no cards)
  and may co-fire `sarathi-llm-failures` or `sarathi-ddb-throttled`.

## Likely Causes

1. Bedrock latency/retries under load stretched triage or digest past the
   budget (retry backoff multiplies wall-clock time).
2. DynamoDB throttling caused long retry/backoff loops inside a step
   (co-fires `sarathi-ddb-throttled`).
3. A large fanout (many workspaces, or one workspace with a very large
   candidate set) exceeded the 2h envelope for legitimate volume reasons.
4. A step is stuck in an unbounded loop or an un-paginated scan over a grown
   table partition.

## Diagnostics

Find the timed-out execution and see where it stalled:

```bash
aws stepfunctions list-executions \
  --profile poc --region us-east-1 \
  --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:sarathi-nightly-pipeline \
  --status-filter TIMED_OUT --max-results 10

aws stepfunctions get-execution-history \
  --profile poc --region us-east-1 \
  --execution-arn <execution_arn> \
  --reverse-order --max-results 25
```

Check per-step Lambda duration to find the slow step:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/Lambda --metric-name Duration \
  --dimensions Name=FunctionName,Value=sarathi-<step> \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics Maximum p99
```

Check Bedrock and DynamoDB pressure over the window:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name LlmFallbackUsed \
  --start-time <start_iso> --end-time <end_iso> \
  --period 900 --statistics Sum

aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/DynamoDB --metric-name ThrottledRequests \
  --dimensions Name=TableName,Value=sarathi \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics Sum
```

## Remediation

1. `[manual]` If Bedrock or DynamoDB pressure is the cause and has cleared,
   re-drive the timed-out execution(s).
2. `[auto-fix]` If a step log shows an un-paginated `table.query`/`scan` that
   grows with data (a full-partition read without `Limit`/`LastEvaluatedKey`
   handling in the hot path), bound it. -> see Code Fix Candidates:
   `unbounded-query`.
3. `[manual]` If the timeout is legitimate volume growth, the fix is an infra
   change: raise the state-machine timeout or shard the fanout. Owned by the
   human and the infra session; do not branch application code for this.

## Code Fix Candidates

- id: unbounded-query
  file: backend/shared/db.py
  symbol: >
    query helpers that paginate with a while-LastEvaluatedKey loop and no upper
    bound (for example the full-partition card reads used by freshness and
    research-context builders)
  issue: >
    A while-loop over LastEvaluatedKey with no cap reads an entire grown
    partition every run; wall-clock time grows unbounded with data.
  fix: >
    Add a sane max-page or max-item bound to the hot-path scans, or push the
    filter into the query so fewer items are materialized.
  test: >
    Unit test with a paginated stub returning N pages; assert the loop stops at
    the bound.
  confidence: low

## Escalation

A one-off timeout that re-drives cleanly needs no escalation. Repeated timeouts
across nights, with no throttling and no code cause, point to volume outgrowing
the pipeline shape: raise to the owner to decide between a longer timeout,
sharded fanout, or step-level concurrency limits.

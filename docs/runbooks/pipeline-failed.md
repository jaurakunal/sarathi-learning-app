---
alarm_name: sarathi-pipeline-failed
severity: sev2
metric: AWS/States/ExecutionsFailed (sarathi-nightly-pipeline)
auto_fixable: true
owning_component: nightly-pipeline
related_alarms:
  - sarathi-feed-stale
  - sarathi-llm-failures
  - sarathi-ddb-throttled
  - sarathi-lambda-errors-triage
  - sarathi-lambda-errors-digest
schema_version: 1
---

# sarathi-pipeline-failed

One or more `sarathi-nightly-pipeline` executions ended in FAILED in the last
hour. The pipeline runs per workspace (fanned out by `sarathi-pipeline-fanout`)
through discover → triage → select → digest → lens → learn. A failure in any
step aborts that workspace's execution.

## Symptoms

- `ExecutionsFailed >= 1` for `sarathi-nightly-pipeline`.
- Usually co-fires `sarathi-feed-stale` for the affected workspace(s), and often
  a per-step `sarathi-lambda-errors-<step>` alarm.
- A specific state in the execution history shows a `States.TaskFailed` or
  Lambda exception.

## Likely Causes

1. A pipeline-step Lambda threw an unhandled exception (triage/select/lens/learn
   fanout item) — the step alarm names which one.
2. The digest Fargate task failed (image pull, OOM, or a Bedrock error inside
   the container) — digest is not a Lambda, so it will not show a
   `sarathi-lambda-errors-*` alarm.
3. Bedrock throttling propagated as a task failure (co-fires
   `sarathi-llm-failures`).
4. DynamoDB throttling mid-step (co-fires `sarathi-ddb-throttled`).
5. A malformed DynamoDB `UpdateExpression` in a step's write path
   (ValidationException) — most likely the latent `update_feed_card_meta` path.

## Diagnostics

Find the failed execution(s):

```bash
aws stepfunctions list-executions \
  --profile poc --region us-east-1 \
  --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:sarathi-nightly-pipeline \
  --status-filter FAILED --max-results 10
```

Get the failure cause and the failing state from the execution history:

```bash
aws stepfunctions describe-execution \
  --profile poc --region us-east-1 \
  --execution-arn <execution_arn>

aws stepfunctions get-execution-history \
  --profile poc --region us-east-1 \
  --execution-arn <execution_arn> \
  --reverse-order --max-results 25
```

Once the failing step is known, pull its Lambda logs (substitute the step name:
`triage`, `select`, `lens`, `learn`, `discover`, `pipeline-fanout`):

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-<step> \
  --start-time <start_epoch_ms> \
  --filter-pattern "?Traceback ?ERROR ?ValidationException ?ThrottlingException" \
  --max-items 25
```

If the failing state is the digest task, inspect the ECS/Fargate task logs:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/ecs/sarathi-digest \
  --start-time <start_epoch_ms> \
  --filter-pattern "?Traceback ?ERROR ?OutOfMemory" \
  --max-items 25
```

## Remediation

1. `[auto-fix]` If a step log shows a `ValidationException` on an
   `UpdateExpression`, apply the null-value handling fix.
   -> see Code Fix Candidates: `feed-card-meta-null`.
2. `[auto-fix]` If the traceback is an unhandled exception on a single fanout
   item that killed the whole step, wrap the per-item work so one bad workspace
   does not fail the batch. -> see Code Fix Candidates: `step-item-isolation`.
3. `[manual]` If the cause is Bedrock or DynamoDB throttling that has cleared,
   re-drive the failed execution(s) with a fresh `start-execution` for the
   affected workspace input.
4. `[manual]` If the digest Fargate task failed on image pull or OOM, this is an
   infra change (task memory / image tag) owned by the human and the infra
   session; do not branch application code.

## Code Fix Candidates

- id: feed-card-meta-null
  file: backend/shared/db.py
  symbol: update_feed_card_meta
  issue: >
    SET-only UpdateExpression with _sanitize_item stripping None values leaves a
    dangling ":vN" reference (ValidationException); empty updates produce a
    malformed "SET ". Latent; already fixed in update_workspace.
  fix: >
    Mirror update_workspace: None -> REMOVE clause, non-None -> SET clause,
    early-return on empty updates.
  test: >
    Unit tests for None value (REMOVE), empty dict (no call), normal value (SET).
  confidence: high

- id: step-item-isolation
  file: backend/pipeline/fanout.py
  symbol: handler (per-workspace / per-item loop)
  issue: >
    An unhandled exception on one fanout item can fail the entire step, taking
    down every workspace in that batch.
  fix: >
    Catch per-item, emit a failure metric, and continue; return a partial-batch
    result the state machine can tolerate.
  test: >
    Unit test with one item that raises; assert siblings still process and a
    failure metric is emitted.
  confidence: medium

## Escalation

If executions fail on two consecutive nightly cycles for the same step, raise to
sev2 and page the owner. If the root cause is a Bedrock or DynamoDB capacity
limit, follow the quota path in `llm-failures.md` / `ddb-throttled.md`. Digest
Fargate infra failures escalate to whoever owns `Dockerfile.digest` and the ECS
task definition.

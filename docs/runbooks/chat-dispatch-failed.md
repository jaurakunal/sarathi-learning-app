---
alarm_name: sarathi-chat-dispatch-failed
severity: sev3
metric: Sarathi/ChatStreamDispatchFailed
auto_fixable: true
auto_remediation: A
auto_remediation_note: >
  Tier A. When the fault maps to the confidence:high `dispatch-retry-and-shape`
  candidate (inconsistent failure return shape plus a missing retry on transient
  invoke errors), implement it on a branch, run `make test` for the touched area
  plus `make api-test` / `make integration-test`, and open a CR for human
  approval. Never auto-merge or auto-deploy. Config drift
  (`STREAM_FUNCTION_NAME`), a concurrency-limit increase, and restoring a lost
  `lambda:InvokeFunction` grant are all `[manual]` infra/CDK actions (B) — an
  A-fix that WIDENS an IAM grant on a least-privilege role stays PR-only and is
  never auto-deployed.
owning_component: streaming-chat
related_alarms:
  - sarathi-chat-chunks-not-delivered
  - sarathi-lambda-errors-chat-dispatch
  - sarathi-lambda-errors-chat-stream
schema_version: 1
---

# sarathi-chat-dispatch-failed

`ChatStreamDispatchFailed >= 1` in a 15-minute window. `chat_dispatch` (the
AppSync resolver for `sendMessage`) writes the user's turn to DynamoDB, then
async-invokes `sarathi-chat-stream` to do the streaming. When that invoke fails,
the turn is written but nothing streams, so the user's message sits with no
reply forming. The dispatcher already catches this and emits the metric.

## Symptoms

- `ChatStreamDispatchFailed >= 1`.
- `chat_dispatch` logs: `Failed to dispatch stream Lambda for conv=... ws=...`.
- The user sees their message posted but no assistant reply ever starts
  (distinct from chunks-not-delivered, where streaming starts then chunks fail).

## Likely Causes

1. `STREAM_FUNCTION_NAME` is wrong/misconfigured (defaults to
   `sarathi-chat-stream`), so the invoke targets a non-existent function.
2. The dispatcher role lost `lambda:InvokeFunction` on `sarathi-chat-stream`.
3. `sarathi-chat-stream` is throttled at the account concurrency limit, so the
   async invoke is rejected.
4. A transient Lambda control-plane error on the `invoke` call.

## Diagnostics

Confirm the failure count:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name ChatStreamDispatchFailed \
  --start-time <start_iso> --end-time <end_iso> \
  --period 900 --statistics Sum
```

See the dispatcher's failure logs:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-chat-dispatch \
  --start-time <start_epoch_ms> \
  --filter-pattern "?\"Failed to dispatch\" ?ResourceNotFound ?AccessDenied ?TooManyRequests" \
  --max-items 25
```

Confirm the configured target name and that the stream function exists:

```bash
aws lambda get-function-configuration \
  --profile poc --region us-east-1 \
  --function-name sarathi-chat-dispatch \
  --query 'Environment.Variables.STREAM_FUNCTION_NAME'

aws lambda get-function-configuration \
  --profile poc --region us-east-1 \
  --function-name sarathi-chat-stream \
  --query 'FunctionArn'
```

Check whether the stream function is being throttled:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/Lambda --metric-name Throttles \
  --dimensions Name=FunctionName,Value=sarathi-chat-stream \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics Sum
```

## Remediation

1. `[manual]` If `STREAM_FUNCTION_NAME` is wrong or the stream function does not
   exist (a rename/deploy drift), fix it in CDK and redeploy.
2. `[manual]` If the dispatcher role lost `lambda:InvokeFunction`, restore the
   grant via CDK.
3. `[manual]` If `sarathi-chat-stream` is hitting the account concurrency limit,
   request a concurrency increase or set reserved concurrency (infra/CDK).
4. `[auto-fix]` Add a bounded retry around the async invoke for transient
   control-plane errors, and make the failure response consistent with the other
   error returns (the current failure path returns a bare string
   `"error:dispatch_failed"` while success returns a dict, which the client can
   mis-handle). -> see Code Fix Candidates: `dispatch-retry-and-shape`.

## Code Fix Candidates

- id: dispatch-retry-and-shape
  file: backend/streaming/chat_dispatch.py
  symbol: handler
  issue: >
    On invoke failure the handler returns the bare string "error:dispatch_failed"
    whereas every success/validation path returns a dict
    {conversationId, turnSeq, status}. The inconsistent shape can break the
    AppSync resolver mapping and the client. There is also no retry on a
    transient invoke error.
  fix: >
    Return the standard dict shape with status "error:dispatch_failed" on
    failure, and add a small bounded retry (2 attempts) around the async invoke
    for transient control-plane errors before giving up.
  test: >
    Unit test that (a) a transient invoke error retried-then-succeeded streams,
    and (b) a hard failure returns the dict shape with the error status, not a
    bare string.
  confidence: high

## Escalation

A config/permission drift after a deploy is a regression: fix-forward or roll
back and note it. Concurrency-limit rejections under real load escalate to the
owner to size reserved concurrency. If both dispatch and chunk delivery are
failing, chat is broadly down; raise to sev2.

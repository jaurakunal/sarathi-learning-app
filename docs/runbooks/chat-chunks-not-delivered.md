---
alarm_name: sarathi-chat-chunks-not-delivered
severity: sev3
metric: Sarathi/PublishChunkFailed
auto_fixable: true
owning_component: streaming-chat
related_alarms:
  - sarathi-chat-dispatch-failed
  - sarathi-lambda-errors-chat-stream
  - sarathi-llm-failures
schema_version: 1
---

# sarathi-chat-chunks-not-delivered

`PublishChunkFailed >= 3` in a 15-minute window. `chat_stream` streams Bedrock
tokens and publishes each chunk to AppSync via an IAM-signed `publishChunk`
mutation. When that publish fails, the user's chat spinner hangs with no text.

## Symptoms

- `PublishChunkFailed >= 3` in 15 minutes.
- Users report chat that "just spins" and never renders a reply.
- `chat_stream` logs: `AppSync publish returned errors`, `AppSync publish HTTP
  <code>`, or `Failed to publish chunk to AppSync`.

## Likely Causes

1. `APPSYNC_ENDPOINT` is empty or misconfigured — the SigV4 request targets ""
   and every publish fails. This is the most common cause and is a config issue,
   not application logic.
2. AppSync throttling or a 4xx/5xx from the AppSync endpoint under load.
3. IAM signing failure (the stream Lambda role lost `appsync:GraphQL` on the
   mutation, or credentials issue).
4. A malformed chunk payload rejected by the GraphQL schema.

## Diagnostics

Confirm the failure count:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name PublishChunkFailed \
  --start-time <start_iso> --end-time <end_iso> \
  --period 900 --statistics Sum
```

See the actual publish error and HTTP code:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-chat-stream \
  --start-time <start_epoch_ms> \
  --filter-pattern "?\"AppSync publish\" ?\"Failed to publish\" ?errors" \
  --max-items 25
```

Check whether `APPSYNC_ENDPOINT` is actually set on the function (read-only):

```bash
aws lambda get-function-configuration \
  --profile poc --region us-east-1 \
  --function-name sarathi-chat-stream \
  --query 'Environment.Variables.APPSYNC_ENDPOINT'
```

## Remediation

1. `[manual]` If `APPSYNC_ENDPOINT` is empty/wrong, fix it in CDK and redeploy.
   This is the top cause and is a config/deploy action owned by the human and
   the infra session (no manual console env edits; go through CDK).
2. `[auto-fix]` Even with the endpoint set, add a guard so an empty
   `APPSYNC_ENDPOINT` fails fast with a clear error and a terminal chunk to the
   client rather than emitting repeated opaque publish failures and hanging the
   user. -> see Code Fix Candidates: `appsync-endpoint-guard`.
3. `[auto-fix]` Add a small bounded retry with backoff around the AppSync
   publish for transient throttles, so a single 429 does not drop a chunk.
   -> see Code Fix Candidates: `publish-chunk-retry`.
4. `[manual]` If it is an IAM permission regression on the stream role, restore
   the `appsync:GraphQL` grant via CDK.

## Code Fix Candidates

- id: appsync-endpoint-guard
  file: backend/streaming/chat_stream.py
  symbol: _publish_chunk / handler
  issue: >
    APPSYNC_ENDPOINT defaults to "" (os.environ.get with an empty fallback).
    When empty, _publish_chunk still builds and sends a request to "", failing
    on every chunk and hanging the client with only PublishChunkFailed metrics.
  fix: >
    At handler start, if APPSYNC_ENDPOINT is empty, log a clear config error,
    emit PublishChunkFailed once, and return an error status. In _publish_chunk,
    short-circuit if the endpoint is empty.
  test: >
    Unit test _publish_chunk / handler with APPSYNC_ENDPOINT="" ; assert it does
    not attempt a network call and returns/records a clear error once.
  confidence: high

- id: publish-chunk-retry
  file: backend/streaming/chat_stream.py
  symbol: _publish_chunk
  issue: >
    A single transient AppSync throttle/5xx drops that chunk with no retry, so a
    brief blip corrupts a stream.
  fix: >
    Wrap the urlopen in a small bounded retry (2-3 attempts, short backoff) for
    429/5xx; keep total added latency small so the stream stays responsive.
  test: >
    Unit test that a first-attempt 429 followed by success results in a
    delivered chunk and no PublishChunkFailed.
  confidence: medium

## Escalation

If the cause is a misconfigured `APPSYNC_ENDPOINT` after a deploy, this is a
regression: fix-forward or roll back the deploy, and note it. Sustained AppSync
throttling that the retry cannot absorb escalates to the owner to review AppSync
limits. Chat being broadly unusable (co-firing dispatch failures) raises to
sev2.

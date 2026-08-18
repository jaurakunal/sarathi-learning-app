---
alarm_name: sarathi-api-5xx
severity: sev2
metric: AWS/ApiGateway/5XXError (sarathi-api)
auto_fixable: partial
owning_component: rest-api
related_alarms:
  - sarathi-api-latency
  - sarathi-lambda-errors-onboarding
  - sarathi-lambda-errors-proposal
  - sarathi-ddb-throttled
  - sarathi-llm-failures
schema_version: 1
---

# sarathi-api-5xx

API Gateway (`sarathi-api`) returned 5XX (502/504/500) to users at least 3 times
in a 5-minute window. Users are seeing broken pages or failed actions right now,
so this is user-facing.

## Symptoms

- `5XXError >= 3` for `sarathi-api`.
- Users report failed loads or actions.
- A backing `sarathi-lambda-errors-<name>` alarm usually co-fires and names the
  handler; `sarathi-api-latency` co-fires when the 5XX is a 504 timeout.

## Likely Causes

1. A backing Lambda threw (502) — the handler traceback names the fault.
2. A backing Lambda exceeded the 29s integration timeout (504) — typically
   onboarding (24k-token generation), proposal (double-LLM), or DELETE /account
   fan-out.
3. Bedrock throttle/outage propagated as a handler exception
   (co-fires `sarathi-llm-failures`).
4. DynamoDB throttling surfaced as a handler error (co-fires
   `sarathi-ddb-throttled`).
5. A malformed response shape or unhandled edge case in a specific route.

## Diagnostics

Confirm the 5XX rate and split 502 vs 504:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/ApiGateway --metric-name 5XXError \
  --dimensions Name=ApiName,Value=sarathi-api \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics Sum

aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/ApiGateway --metric-name Latency \
  --dimensions Name=ApiName,Value=sarathi-api \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics p99 Maximum
```

Identify which handler is erroring by scanning the API Gateway access/execution
logs, or by checking which `sarathi-lambda-errors-*` alarm is also in ALARM,
then read that handler's log group:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-<name> \
  --start-time <start_epoch_ms> \
  --filter-pattern "?Traceback ?ERROR ?Task timed out ?ValidationException" \
  --max-items 25
```

## Remediation

1. `[auto-fix]` If the backing handler threw a fixable code error (for example a
   `ValidationException` on an `UpdateExpression`, or a handled edge case), fix
   it in that handler. -> route via `lambda-errors.md` Code Fix Candidates.
2. `[manual]` If the 5XX is a 504 timeout on a synchronous-LLM route
   (onboarding/proposal), treat as `sarathi-api-latency`; the durable fix is to
   move that work off the request path, which is a design change, not a hotfix.
3. `[manual]` If Bedrock or DynamoDB throttling is the driver, follow
   `llm-failures.md` / `ddb-throttled.md`; the code is usually not at fault.

## Code Fix Candidates

Deferred to the specific backing handler. Once diagnostics name the handler,
load `lambda-errors.md` and use its Code Fix Candidates (`feed-card-meta-null`,
`chat-stream-keyerror`, `onboarding-*`). No 5XX-specific code fix lives at the
API Gateway layer.

## Escalation

This alarm is user-facing; if the 5XX rate is sustained (more than two
consecutive 5-minute windows) and no clean fix is in flight, page the owner at
sev2. A brief 504 spike during a known Bedrock throttle that self-recovers can
stay sev3 with a note.

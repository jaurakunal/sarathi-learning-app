---
alarm_name: sarathi-api-latency
alarm_name_pattern: "sarathi-lambda-slow-*"
severity: sev3
metric: AWS/ApiGateway/Latency (sarathi-api) ; AWS/Lambda/Duration p99 (per fn)
auto_fixable: partial
auto_remediation: A
auto_remediation_note: >
  Tier A is CONDITIONAL and NARROW: the only fix the agent may implement here is
  the known N+1 / hot-path fan-out bound (`hotpath-query-bound` — a request-path
  DynamoDB read that paginates a growing partition or does sequential per-item
  ops). When diagnostics clearly localize that pattern, implement on a branch,
  run `make test` for the touched area plus `make api-test` /
  `make integration-test`, and open a CR for human approval. Everything else is
  B: Bedrock generation latency, retry/backoff inflation, or a
  synchronous-LLM-on-the-request-path design issue (onboarding/proposal) is
  capacity/design, so run diagnostics and REPORT only. NEVER auto-merge or
  auto-deploy. Note: `hotpath-query-bound` is currently confidence:low, so until
  it is promoted to high the agent proposes it rather than implements it — it
  qualifies for A only once the specific fan-out fix is recognized and
  high-confidence.
owning_component: rest-api
related_alarms:
  - sarathi-api-5xx
  - sarathi-llm-failures
  - sarathi-lambda-errors-onboarding
  - sarathi-lambda-errors-proposal
schema_version: 1
---

# sarathi-api-latency / sarathi-lambda-slow-<name>

`sarathi-api-latency` fires when API Gateway p99 latency crosses 25s for two
5-minute periods, approaching the 29s integration timeout. The per-function
`sarathi-lambda-slow-<name>` alarms fire on the same threshold for the three
synchronous-LLM handlers wired with duration alarms: `onboarding`, `proposal`,
`chat`. Crossing 29s turns into a 504 and trips `sarathi-api-5xx`.

## Symptoms

- p99 latency > 25000 ms sustained.
- Users see spinners that resolve slowly or time out.
- `sarathi-lambda-slow-onboarding` / `-proposal` / `-chat` name the slow handler
  directly.

## Likely Causes

1. Bedrock generation latency under load (onboarding generates up to 24k tokens;
   proposal makes two sequential LLM calls) — co-fires `sarathi-llm-failures`
   or shows a rising `LlmFallbackUsed`.
2. DELETE /account fan-out doing many sequential DynamoDB operations in the
   request path.
3. A retry/backoff loop (Bedrock or DynamoDB) inflating wall-clock time.
4. An un-paginated or growing DynamoDB read in the hot path.

## Diagnostics

Confirm p99 and find the slow handler:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/ApiGateway --metric-name Latency \
  --dimensions Name=ApiName,Value=sarathi-api \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics p99 Maximum

aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/Lambda --metric-name Duration \
  --dimensions Name=FunctionName,Value=sarathi-<name> \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics p99 Maximum
```

Check Bedrock pressure and look for slow-path log lines:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name LlmFallbackUsed \
  --start-time <start_iso> --end-time <end_iso> \
  --period 900 --statistics Sum

aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-<name> \
  --start-time <start_epoch_ms> \
  --filter-pattern "?REPORT ?Duration ?retry ?backoff" \
  --max-items 20
```

## Remediation

1. `[auto-fix]` If a hot-path DynamoDB read is un-paginated/growing, bound it.
   -> see Code Fix Candidates: `hotpath-query-bound`.
2. `[manual]` If the slow handler is onboarding or proposal doing synchronous
   LLM work, the durable fix is to move generation off the request path (async +
   poll, or streaming), a design change owned by the human. Do not attempt a
   hotfix that only trims tokens without confirming quality impact.
3. `[manual]` If Bedrock latency under load is the driver, follow
   `llm-failures.md`; consider capacity/quota rather than code.

## Code Fix Candidates

- id: hotpath-query-bound
  file: backend/api (the named slow handler)
  symbol: the request-path DynamoDB read identified in diagnostics
  issue: >
    A request-path query paginates over a growing partition or does sequential
    per-item operations, so latency scales with data.
  fix: >
    Add a Limit / early-exit, or batch the operations; keep the request path
    O(1) in table growth.
  test: >
    Unit test the handler path with a large stubbed result set; assert the read
    is bounded.
  confidence: low

## Escalation

Latency alone (no 5XX) that tracks a known Bedrock load spike and recovers stays
sev3 with a note. Sustained latency that starts producing 504s escalates via
`api-5xx.md`. A repeated onboarding/proposal timeout pattern is a design signal:
raise to the owner to prioritize moving synchronous LLM work off the request
path.

---
alarm_name: sarathi-llm-failures
severity: sev2
metric: Sarathi/LlmCallFailed
auto_fixable: false
auto_remediation: B
auto_remediation_note: >
  Tier B. This is a Bedrock dependency signal — throttle, regional outage, or
  model-access change — so the agent runs diagnostics and REPORTS only; there is
  no code fix at the dependency layer and changing the shared client's retry
  behavior during a live throttle would make it worse. If diagnostics show the
  "failures" are actually malformed-request ValidationExceptions (a caller bug,
  not an outage), that is not remediated here: hand it to the A-conditional
  `lambda-errors.md` path (`onboarding-history-order`), where the confidence gate
  and CR flow apply. This alarm's own tier stays B.
owning_component: bedrock-dependency
related_alarms:
  - sarathi-feed-stale
  - sarathi-pipeline-failed
  - sarathi-api-5xx
  - sarathi-chat-chunks-not-delivered
schema_version: 1
---

# sarathi-llm-failures

`LlmCallFailed >= 5` in a 15-minute window. The metric is emitted when a Bedrock
call fails and the fallback model also returned None, so both the primary and
fallback path failed. Feed quality, chat, onboarding, and proposals are all
degraded when this fires.

## Symptoms

- `LlmCallFailed >= 5` in 15 minutes.
- Rising `LlmFallbackUsed` in the run-up (the system was already leaning on the
  fallback before both failed).
- Downstream: `sarathi-feed-stale`, `sarathi-pipeline-failed`,
  `sarathi-api-5xx`, chat errors.

## Likely Causes

1. Bedrock throttling under load — the most common cause; the account hit a
   model invocation rate/token quota in us-east-1.
2. A Bedrock regional outage or model-specific degradation (Kimi/Sonnet).
3. A malformed request the model rejects (bad message history, oversized
   context) — this looks like a failure but is a code bug, not a Bedrock outage.
4. Model access/permission change (a model id disabled or access revoked).

## Diagnostics

Confirm the failure and fallback trend:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name LlmCallFailed \
  --start-time <start_iso> --end-time <end_iso> \
  --period 900 --statistics Sum

aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name LlmFallbackUsed \
  --start-time <start_iso> --end-time <end_iso> \
  --period 900 --statistics Sum
```

Find the failing call and its error class across the LLM callers (triage, digest
container, chat-stream, onboarding, proposal):

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-<name> \
  --start-time <start_epoch_ms> \
  --filter-pattern "?ThrottlingException ?ModelStreamError ?ValidationException ?AccessDenied ?Bedrock" \
  --max-items 25
```

Distinguish throttle (capacity) from validation (code):

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-triage \
  --start-time <start_epoch_ms> \
  --filter-pattern "ThrottlingException" \
  --max-items 10
```

## Remediation

1. `[manual]` If the errors are `ThrottlingException`, this is capacity: reduce
   pipeline concurrency temporarily, and/or request a Bedrock quota increase for
   the affected model in us-east-1. Do not treat as a code bug.
2. `[manual]` If it is a regional Bedrock outage, wait it out and re-drive
   affected pipeline executions once healthy (see `feed-stale.md` /
   `pipeline-failed.md`).
3. `[manual]` If `AccessDenied` / model-disabled, restore model access (IAM /
   Bedrock model access) via CDK/config; owned by the human.
4. `[auto-fix-adjacent]` If the failures are `ValidationException` from a
   malformed request (bad message history), that is not really an LLM outage:
   route it to `lambda-errors.md` and fix the calling handler
   (`onboarding-history-order`). This alarm's own auto_fixable stays false;
   the fix lives in the caller's runbook.

## Code Fix Candidates

None at the dependency layer. If diagnostics show the "failures" are actually
malformed-request `ValidationException`s, hand off to `lambda-errors.md`
(`onboarding-history-order`) rather than fixing anything in the Bedrock client.
The shared client already does primary+fallback and retries; changing its retry
behavior during a live throttle would make throttling worse, so do not.

## Escalation

Sustained Bedrock failures affecting the feed and chat are sev2. If it is a
quota ceiling, the quota-increase request is the real remediation and can take
time, so set expectations with the owner. If it is a confirmed Bedrock regional
outage, this is upstream: track the AWS Health Dashboard and re-drive on
recovery.

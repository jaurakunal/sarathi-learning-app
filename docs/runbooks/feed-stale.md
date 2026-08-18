---
alarm_name: sarathi-feed-stale
severity: sev2
metric: Sarathi/FeedFreshnessBreach
auto_fixable: true
owning_component: nightly-pipeline
related_alarms:
  - sarathi-pipeline-failed
  - sarathi-llm-failures
  - sarathi-lambda-errors-canary-freshness
  - sarathi-lambda-errors-triage
  - sarathi-lambda-errors-discover
schema_version: 1
---

# sarathi-feed-stale

The single most important check. The freshness canary
(`sarathi-canary-freshness`, runs 04:00 UTC) counts feed cards created in the
last 24h across active workspaces and emits `FeedFreshnessBreach=1` when there
are active workspaces but zero fresh cards. `treatMissingData` is `BREACHING`,
so a canary that never ran also fires this alarm. This catches the app's
signature failure: a nightly pipeline that reports SUCCEEDED but produced
nothing.

## Symptoms

- Users see the same feed as yesterday; no new cards this morning.
- `FeedFreshnessBreach` metric = 1 for the 24h period.
- `sarathi-pipeline-failed` may be quiet (the pipeline "succeeded" silently), or
  it may also be firing (hard failure).
- `FeedCardsLast24h` = 0 while `ActiveWorkspaces` > 0 on the Sārathi dashboard.

## Likely Causes

1. Bedrock throttling or outage during `triage` or `digest`, so no candidate
   became a card (often co-fires `sarathi-llm-failures`).
2. `discover` returned zero new candidates (upstream source drought or a source
   fetch failure), so nothing entered triage.
3. A workspace was auto-paused by the interruption logic, so the canary counts
   it as inactive and no cards are expected (may be a false positive worth
   confirming, not a code fault).
4. A malformed DynamoDB write in the card-writing path threw and was swallowed,
   so cards were generated but not persisted (see Code Fix Candidates:
   `feed-card-meta-null`).
5. The canary itself failed to run (IAM, timeout, or a `db` import error) —
   missing data is treated as a breach.

## Diagnostics

Confirm the breach and see the per-workspace breakdown the canary logged:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-canary-freshness \
  --start-time <start_epoch_ms> \
  --filter-pattern "FEED FRESHNESS BREACH" \
  --max-items 5
```

Check whether the nightly pipeline actually ran and how it ended:

```bash
aws stepfunctions list-executions \
  --profile poc --region us-east-1 \
  --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:sarathi-nightly-pipeline \
  --max-results 5
```

Look at the pipeline output metrics for the last day to localize the drop
(discover vs triage vs digest):

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name CandidatesDiscovered \
  --start-time <start_iso> --end-time <end_iso> \
  --period 86400 --statistics Sum

aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name PapersWorthReading \
  --start-time <start_iso> --end-time <end_iso> \
  --period 86400 --statistics Sum

aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name FeedCardsGenerated \
  --start-time <start_iso> --end-time <end_iso> \
  --period 86400 --statistics Sum
```

Check Bedrock failures over the same window:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace Sarathi --metric-name LlmCallFailed \
  --start-time <start_iso> --end-time <end_iso> \
  --period 900 --statistics Sum
```

Scan triage and digest logs for throttling or write errors:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-triage \
  --start-time <start_epoch_ms> \
  --filter-pattern "?ThrottlingException ?ValidationException ?Traceback" \
  --max-items 20
```

## Remediation

1. `[manual]` If the cause is a Bedrock throttle/outage that has since cleared,
   re-drive the failed workspace(s): start a new execution of
   `sarathi-nightly-pipeline` for the affected users. This is an operator action
   because it consumes Bedrock capacity and writes production data.
2. `[manual]` If a workspace was auto-paused unexpectedly, confirm with the user
   / check the pause reason, then un-pause via the settings path. Not a code
   fault; do not branch a fix.
3. `[auto-fix]` If the diagnostic logs show a `ValidationException` on an
   `UpdateExpression` in the card-writing path (cards generated but not saved),
   apply the null-value handling fix. -> see Code Fix Candidates:
   `feed-card-meta-null`.
4. `[auto-fix]` If `discover` threw on a single bad source and aborted the whole
   batch, harden the per-source loop to continue past one failed source.
   -> see Code Fix Candidates: `discover-source-isolation`.
5. `[manual]` If the canary itself failed (missing metric), fix the canary error
   first (treat as a `sarathi-lambda-errors-canary-freshness` incident) before
   trusting freshness numbers again.

## Code Fix Candidates

- id: feed-card-meta-null
  file: backend/shared/db.py
  symbol: update_feed_card_meta
  issue: >
    Builds a SET-only UpdateExpression, then runs values through
    _sanitize_item which drops None values. A None in `updates` leaves a
    dangling ":vN" reference (ValidationException); an empty `updates` produces
    the malformed "SET ". This is the same class of bug that was already fixed
    in update_workspace, but it remains LATENT here.
  fix: >
    Mirror update_workspace: route None values to a REMOVE clause instead of
    SET, build separate set_parts / remove_parts, and return early when there
    is nothing to update.
  test: >
    Unit test update_feed_card_meta with (a) a None value -> asserts REMOVE
    clause and no dangling value ref, (b) an empty dict -> asserts no
    update_item call, (c) a normal value -> asserts SET clause unchanged.
  confidence: high

- id: discover-source-isolation
  file: backend/pipeline/discover.py
  symbol: handler (per-source fetch loop)
  issue: >
    A single failing source can raise and abort the whole discover step,
    starving triage of candidates.
  fix: >
    Wrap each source fetch in try/except, log and metric the failed source,
    continue to the next.
  test: >
    Unit test with a stubbed source that raises; assert the remaining sources
    still yield candidates and one failure metric is emitted.
  confidence: medium

## Escalation

If Bedrock throttling is the root cause and persists across two nightly cycles,
this is a capacity/quota issue: check the Bedrock service quota for the account
in us-east-1 and open a limit-increase request. If the feed is stale for more
than 48h with no identified code cause, raise to sev2 and page the owner. A
false-positive from an intentionally paused single-user workspace does not
warrant escalation; note it and resolve.

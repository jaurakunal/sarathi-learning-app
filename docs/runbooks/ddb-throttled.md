---
alarm_name: sarathi-ddb-throttled
severity: sev3
metric: AWS/DynamoDB/ThrottledRequests (TableName=sarathi)
auto_fixable: false
owning_component: datastore
related_alarms:
  - sarathi-api-5xx
  - sarathi-api-latency
  - sarathi-pipeline-failed
  - sarathi-pipeline-timed-out
schema_version: 1
---

# sarathi-ddb-throttled

The `sarathi` single table is throttling requests (`ThrottledRequests >= 1` in a
5-minute window). Throttling ripples into every reader: API latency/5XX and
pipeline failures/timeouts. This is almost always a capacity or access-pattern
issue, not an application-logic bug, so it is not auto-fixable.

## Symptoms

- `ThrottledRequests >= 1` for table `sarathi`.
- Co-firing `sarathi-api-latency` / `sarathi-api-5xx` and/or
  `sarathi-pipeline-*` alarms.
- Handler logs show `ProvisionedThroughputExceededException` or
  `ThrottlingException` from DynamoDB.

## Likely Causes

1. A hot partition: many requests to one PK (for example the freshness canary or
   research-context builder scanning one large feed partition, or a single very
   active workspace).
2. The nightly pipeline fanout hitting the table hard in a burst.
3. On-demand table adapting too slowly to a sudden spike, or provisioned
   capacity set too low for current load.
4. An un-paginated scan repeatedly reading a large partition (amplifies read
   pressure).

## Diagnostics

Confirm throttling and see which operation:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/DynamoDB --metric-name ThrottledRequests \
  --dimensions Name=TableName,Value=sarathi \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics Sum

aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/DynamoDB --metric-name ReadThrottleEvents \
  --dimensions Name=TableName,Value=sarathi \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics Sum

aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/DynamoDB --metric-name WriteThrottleEvents \
  --dimensions Name=TableName,Value=sarathi \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics Sum
```

Inspect table capacity mode and settings (read-only):

```bash
aws dynamodb describe-table \
  --profile poc --region us-east-1 \
  --table-name sarathi \
  --query 'Table.{Billing:BillingModeSummary,Capacity:ProvisionedThroughput,Status:TableStatus,Items:ItemCount}'
```

Find the request source in the co-firing component's logs:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-<name> \
  --start-time <start_epoch_ms> \
  --filter-pattern "?ProvisionedThroughputExceeded ?ThrottlingException" \
  --max-items 20
```

## Remediation

1. `[manual]` If the table is provisioned and capacity is too low, raise
   read/write capacity or switch to on-demand. This is an infra/CDK change owned
   by the human and the infra session (no manual console capacity edits; go
   through CDK).
2. `[manual]` If a hot partition is the cause, the fix is an access-pattern /
   data-model change (spread the partition, add a GSI, cache), a design change
   owned by the human.
3. `[manual]` If the pipeline burst is the driver, add step-level concurrency
   limits or stagger the fanout (infra change).

## Code Fix Candidates

None. This alarm is a capacity/access-pattern signal, not an application-logic
fault. The agent stops after diagnostics and posts findings (which operation,
which source, current capacity mode) for a human. If diagnostics reveal an
un-paginated hot-path scan amplifying the pressure, note it and cross-reference
`pipeline-timed-out.md` Code Fix Candidate `unbounded-query`, but do not treat
capacity as a code bug.

## Escalation

If throttling is sustained and cascading into user-facing 5XX, raise to sev2 and
page the owner to make the capacity/data-model call. Persistent throttling under
normal load means the table shape has outgrown its access pattern; that is a
design conversation, not an incident hotfix.

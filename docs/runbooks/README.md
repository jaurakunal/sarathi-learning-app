---
doc_type: runbook_index
schema_version: 1
generated_for: agentic_and_human_consumers
account: "123456789012"
region: us-east-1
aws_profile: poc
sns_topic: sarathi-alarms
metric_namespace: Sarathi
---

# Sārathi Operational Runbooks

These runbooks are written for two readers: the human on call, and an ops agent
(`.claude/agents/sarathi-ops.md`) that parses them deterministically. Every
runbook maps to one CloudWatch alarm (or one alarm family) wired to the
`sarathi-alarms` SNS topic, which fans out to Slack through AWS Chatbot.

The rule that keeps both readers safe: an agent may run every command in the
`## Diagnostics` section without asking, because those are read-only. It may
implement a `[auto-fix]` remediation step only on a fresh feature branch with a
test, and it may never apply a `[manual]` step or merge to mainline on its own.
A human owns the merge and the deploy. See `OPS_AGENT_DESIGN.md` for the full
guardrail model.

## Parsing contract

An agent reads a runbook as follows, and should fail loudly rather than guess if
any of these invariants do not hold:

1. **Frontmatter.** The file opens with a YAML block fenced by `---` lines. The
   required keys are `alarm_name` (or `alarm_name_pattern` for a family),
   `severity` (`sev2` | `sev3` | `sev4`), `metric`, `auto_fixable` (bool),
   `owning_component`, and `related_alarms` (list, possibly empty). Treat any
   additional keys as advisory.
2. **Sections.** The body is divided by level-2 markdown headings drawn from
   this fixed, ordered set. Every runbook contains all six, in this order:
   `## Symptoms`, `## Likely Causes`, `## Diagnostics`, `## Remediation`,
   `## Code Fix Candidates`, `## Escalation`. Section boundaries are the `## `
   headings; nothing else uses `## `.
3. **Diagnostics.** Every fenced ```bash block inside `## Diagnostics` is a
   runnable, read-only command. Angle-bracket placeholders (`<user_id>`,
   `<execution_arn>`, `<lambda_short_name>`, `<start_epoch_ms>`, ...) must be
   substituted from the incident payload before running. All commands already
   carry `--profile poc --region us-east-1`. A command that would mutate state
   never appears here; mutations live in `## Remediation` behind a `[manual]`
   tag.
4. **Remediation.** An ordered (numbered) list. Each step begins with exactly
   one action-class tag in brackets:
   - `[auto-fix]` — a code change in this repo that the agent may implement on a
     branch with a test. The specific file and function are named in
     `## Code Fix Candidates`.
   - `[manual]` — an AWS-side action (console, mutating CLI, capacity change,
     re-drive, config edit) that only a human performs. The agent surfaces it in
     its summary but does not execute it.
   A step may carry a trailing `-> see Code Fix Candidates: <id>` pointer.
5. **Code Fix Candidates.** Zero or more entries. Each entry is a bullet whose
   first line is `- id: <slug>` followed by indented keyed lines: `file:`,
   `symbol:`, `issue:`, `fix:`, `test:`, and `confidence:` (`high` | `medium` |
   `low`). The agent only ever acts on `confidence: high` candidates without
   asking; medium/low are proposed in the summary for a human to confirm.
6. **Escalation.** Free-text plus, where relevant, the next SEV level and who to
   notify. Not machine-critical; render for the human.

If `auto_fixable: false`, the agent should expect `## Code Fix Candidates` to
read `None.` and should stop after diagnostics, posting findings for a human.

## Alarm → runbook routing table

An incoming alarm name is matched first against exact `alarm_name` values, then
against `alarm_name_pattern` (glob) for families. First exact match wins.

| Alarm name | Runbook file | Severity | Auto-fixable |
|---|---|---|---|
| `sarathi-feed-stale` | `feed-stale.md` | sev2 | yes |
| `sarathi-pipeline-failed` | `pipeline-failed.md` | sev2 | yes |
| `sarathi-pipeline-timed-out` | `pipeline-timed-out.md` | sev3 | partial |
| `sarathi-lambda-errors-*` | `lambda-errors.md` | sev3 | yes |
| `sarathi-api-5xx` | `api-5xx.md` | sev2 | partial |
| `sarathi-api-latency` | `api-latency.md` | sev3 | partial |
| `sarathi-lambda-slow-*` | `api-latency.md` | sev3 | partial |
| `sarathi-ddb-throttled` | `ddb-throttled.md` | sev3 | no |
| `sarathi-llm-failures` | `llm-failures.md` | sev2 | no |
| `sarathi-chat-chunks-not-delivered` | `chat-chunks-not-delivered.md` | sev3 | yes |
| `sarathi-chat-dispatch-failed` | `chat-dispatch-failed.md` | sev3 | yes |

The `sarathi-lambda-errors-*` family covers all 29 per-function error alarms.
`lambda-errors.md` carries a per-function annex for the handlers whose failure
modes are specific enough to have a known code fix: `onboarding`, `settings`,
`chat-stream`, and `pre-signup`.

## Fixed facts these runbooks assume

- Account `123456789012`, region `us-east-1`, CLI profile `poc`.
- Nightly Step Functions state machine: `sarathi-nightly-pipeline`
  (discover → triage → select → digest → lens → learn, fanned out per
  workspace by `sarathi-pipeline-fanout`; the digest step runs as a Fargate task
  built from `Dockerfile.digest`, not a Lambda).
- DynamoDB single table: `sarathi`.
- Custom metrics are emitted via EMF (namespace `Sarathi`) from
  `backend/shared/metrics.py`; there is no synchronous `PutMetricData`, so a
  missing metric usually means the emitting Lambda never ran.
- Lambdas are named `sarathi-<name>`; their log groups are
  `/aws/lambda/sarathi-<name>`.
- Bedrock models in use: Kimi and Sonnet (generation), Titan (embeddings).

## Known recurring failure classes (cross-runbook)

- Bedrock throttling under load — surfaces as `sarathi-llm-failures`,
  `sarathi-feed-stale`, and onboarding/proposal latency.
- Malformed DynamoDB `UpdateExpression` — the pattern was fixed in
  `db.update_workspace` but remains **latent in `db.update_feed_card_meta`**
  (no null-value REMOVE handling, no empty-updates guard). Referenced from
  `lambda-errors.md` and `feed-stale.md`.
- Onboarding Bedrock message-history ordering and JSON-parse failures — see
  `lambda-errors.md` onboarding annex.
- `chat_stream` `KeyError` on a malformed dispatch payload, and hung streams
  when `APPSYNC_ENDPOINT` is empty — see `chat-chunks-not-delivered.md`.

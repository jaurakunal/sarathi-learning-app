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
   `auto_remediation` (`A` | `B` | `C`, see below), `owning_component`, and
   `related_alarms` (list, possibly empty). An optional `auto_remediation_note`
   (string) qualifies the tier when it is conditional. Treat any additional keys
   as advisory.
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

## Auto-remediation tiers

`auto_remediation` says how far the agent is allowed to act once it has
diagnosed the incident. It is orthogonal to `auto_fixable` (which only says
whether a code fix exists): a runbook can have a high-confidence code fix and
still be tier B when the alarm's usual root cause is capacity or data rather than
that code path. There are three tiers.

- **A — code/config bug the agent can deterministically fix.** The root cause is
  a bug in this repo. The agent may branch, implement the fix, run the unit
  tests (`make test` / `python -m pytest tests/` for the touched area) AND the
  integration tests (`make api-test` and `make integration-test`), and if green
  OPEN A CR for human approval. It NEVER auto-merges and NEVER auto-deploys.
  Tier A is often CONDITIONAL: the agent acts as A only when the diagnosed fault
  maps to a `Code Fix Candidate` marked `confidence: high`; otherwise it falls
  back to B (diagnose and report). Each runbook's `auto_remediation_note` states
  its condition. A fix that would WIDEN an IAM permission on a least-privilege
  role (for example adding a DynamoDB or AppSync action) is still PR-only and
  must never be auto-deployed — the human approves the CR, and the deploy happens
  through the normal CDK path.
- **B — capacity/external/data, no code fix.** The root cause is a Bedrock
  throttle/outage, a DynamoDB capacity/access-pattern problem, a source drought,
  a config/env value, or legitimate volume growth. The agent runs the read-only
  diagnostics and REPORTS its findings and likely cause to Slack. It makes no
  code change.
- **C — human-only, never auto-touch.** Auth/security/IAM blast-radius (for
  example the Cognito `pre-signup` trigger, where a bad fix blocks all
  login/signup). The agent stops immediately, pages a human, and takes no
  automated action — no diagnostics-driven change, no branch, no CR.

## Alarm → runbook routing table

An incoming alarm name is matched first against exact `alarm_name` values, then
against `alarm_name_pattern` (glob) for families. First exact match wins.

| Alarm name | Runbook file | Severity | Auto-fixable | Tier |
|---|---|---|---|---|
| `sarathi-feed-stale` | `feed-stale.md` | sev2 | yes | B |
| `sarathi-pipeline-failed` | `pipeline-failed.md` | sev2 | yes | B (A only if a step raised a code exception mapping to a high-confidence fix) |
| `sarathi-pipeline-timed-out` | `pipeline-timed-out.md` | sev3 | partial | B |
| `sarathi-lambda-errors-*` | `lambda-errors.md` | sev3 | yes | A-conditional (else B); `pre-signup` is C |
| `sarathi-api-5xx` | `api-5xx.md` | sev2 | partial | A-conditional (else B) |
| `sarathi-api-latency` | `api-latency.md` | sev3 | partial | A only for the N+1 fan-out fix, else B |
| `sarathi-lambda-slow-*` | `api-latency.md` | sev3 | partial | A only for the N+1 fan-out fix, else B |
| `sarathi-ddb-throttled` | `ddb-throttled.md` | sev3 | no | B |
| `sarathi-llm-failures` | `llm-failures.md` | sev2 | no | B |
| `sarathi-chat-chunks-not-delivered` | `chat-chunks-not-delivered.md` | sev3 | yes | A |
| `sarathi-chat-dispatch-failed` | `chat-dispatch-failed.md` | sev3 | yes | A |

The `sarathi-lambda-errors-*` family covers all 29 per-function error alarms.
`lambda-errors.md` carries a per-function annex for the handlers whose failure
modes are specific enough to have a known code fix: `onboarding`, `settings`,
`chat-stream`, and `pre-signup`. That annex also carries per-handler tiers:
`onboarding`, `settings`, and `chat-stream` are A-conditional (act only on a
high-confidence candidate, else report), while `pre-signup` is tier C
(auth/security blast-radius — human-only, the agent never touches it).
"A-conditional" always means the agent falls back to B (diagnose and report) when
the fault does not map to a `confidence: high` Code Fix Candidate, and even a
qualifying A-fix opens a CR rather than merging or deploying.

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

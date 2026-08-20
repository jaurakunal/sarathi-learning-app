---
alarm_name_pattern: "sarathi-lambda-errors-*"
severity: sev3
metric: AWS/Lambda/Errors (per function)
auto_fixable: true
auto_remediation: A
auto_remediation_note: >
  Tier A is CONDITIONAL. Only act as A (implement the fix on a branch, run
  `make test` for the touched area plus `make api-test` / `make integration-test`,
  then open a CR) when the traceback maps to a known Code Fix Candidate marked
  confidence:high (today: `feed-card-meta-null`, `chat-stream-keyerror`).
  Otherwise fall back to B: run diagnostics and REPORT only. In particular, a
  ThrottlingException (Bedrock/DynamoDB) or a missing/empty env var is B — it is
  capacity/config, not a code fix. NEVER auto-merge or auto-deploy; the CR is for
  human approval. See the per-function annex for handler-specific tiers
  (pre-signup is C, human-only). If a proposed fix would WIDEN an IAM grant on a
  least-privilege role (e.g. adding a DynamoDB or AppSync action), it is still
  PR-only and must never be auto-deployed.
owning_component: per-function
related_alarms:
  - sarathi-api-5xx
  - sarathi-llm-failures
  - sarathi-ddb-throttled
schema_version: 1
---

# sarathi-lambda-errors-<name>

Generic runbook for the 29 per-function error alarms. The alarm name carries the
short function name: `sarathi-lambda-errors-onboarding` -> function
`sarathi-onboarding` -> log group `/aws/lambda/sarathi-onboarding`. The alarm
fires on `Errors >= 1` in a 5-minute window. Diagnose generically first, then
consult the per-function annex below for handlers with known failure modes.

Extract `<name>` from the alarm name, set `<fn>` = `sarathi-<name>`, and
`<log_group>` = `/aws/lambda/sarathi-<name>`.

## Symptoms

- `Errors >= 1` for `<fn>` in a 5-minute period.
- For an API-backed function (`api-*`, `chat`, `onboarding`, `settings`), users
  likely also see failures and `sarathi-api-5xx` may co-fire.
- For a pipeline step, `sarathi-pipeline-failed` may co-fire.

## Likely Causes

1. Unhandled exception in the handler (the traceback names the line).
2. A downstream dependency error: Bedrock (throttle/validation), DynamoDB
   (throttle/validation), S3, or AppSync.
3. A malformed DynamoDB `UpdateExpression` (ValidationException) — check the
   `update_feed_card_meta` path first, it is the known latent one.
4. A bad-input `KeyError`/`TypeError` from an unexpected event shape.
5. Cold-start import error or a missing/empty environment variable.

## Diagnostics

Confirm the error count and window:

```bash
aws cloudwatch get-metric-statistics \
  --profile poc --region us-east-1 \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=sarathi-<name> \
  --start-time <start_iso> --end-time <end_iso> \
  --period 300 --statistics Sum
```

Pull the tracebacks:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-<name> \
  --start-time <start_epoch_ms> \
  --filter-pattern "?Traceback ?ERROR ?Exception ?ValidationException ?ThrottlingException ?KeyError" \
  --max-items 25
```

Classify the top exception type to route the fix:

```bash
aws logs filter-log-events \
  --profile poc --region us-east-1 \
  --log-group-name /aws/lambda/sarathi-<name> \
  --start-time <start_epoch_ms> \
  --filter-pattern "ValidationException" \
  --max-items 10
```

## Remediation

1. `[auto-fix]` `ValidationException` on an `UpdateExpression` -> apply the
   null-value handling fix. -> see Code Fix Candidates: `feed-card-meta-null`.
2. `[auto-fix]` `KeyError` on the event payload in `chat-stream` -> use `.get`
   with validation and fail the turn cleanly. -> see Code Fix Candidates:
   `chat-stream-keyerror`.
3. `[auto-fix]` Onboarding JSON-parse or message-history ordering error ->
   see the onboarding annex and Code Fix Candidates: `onboarding-history-order`,
   `onboarding-json-parse`.
4. `[manual]` `ThrottlingException` from Bedrock or DynamoDB -> treat as the
   corresponding dependency incident (`llm-failures.md` / `ddb-throttled.md`);
   the code is usually fine, the capacity is not.
5. `[manual]` Missing/empty environment variable (for example an empty
   `APPSYNC_ENDPOINT`) -> this is a deploy/config fix via CDK, owned by the
   human and the infra session.

## Code Fix Candidates

- id: feed-card-meta-null
  file: backend/shared/db.py
  symbol: update_feed_card_meta
  issue: >
    SET-only UpdateExpression; _sanitize_item drops None values, leaving a
    dangling ":vN" (ValidationException); empty updates produce "SET ". Latent;
    update_workspace already handles this correctly.
  fix: >
    Mirror update_workspace: None -> REMOVE, non-None -> SET, early-return on
    empty updates.
  test: >
    Unit tests: None value emits REMOVE and no dangling ref; empty dict makes no
    call; normal value emits SET.
  confidence: high

- id: chat-stream-keyerror
  file: backend/streaming/chat_stream.py
  symbol: handler
  issue: >
    Reads event["user_id"], event["conv_id"], event["message"], event["turn_seq"]
    by direct index. A malformed dispatch payload raises KeyError, which counts
    as a Lambda error and leaves the client's turn hung.
  fix: >
    Validate required keys up front; on a missing key, publish a terminal error
    chunk for the turn (if conv_id is known) and return an error status instead
    of raising.
  test: >
    Unit test handler with a payload missing "message"; assert no unhandled
    raise and an error status is returned.
  confidence: high

- id: onboarding-history-order
  file: backend/api/onboarding.py
  symbol: _handle_user_stage / _handle_workspace_stage
  issue: >
    Bedrock rejects a message history that ends with an assistant message. The
    hydration guards ("no new message but turns exist") exist; new call paths
    that append turns can still produce a history ending on assistant.
  fix: >
    Before calling call_llm_multi, assert/repair that llm_messages ends with a
    user turn (drop a trailing assistant turn or append the priming user turn).
  test: >
    Unit test that a turn list ending in an assistant response is repaired to
    end on a user turn before the LLM call.
  confidence: medium

- id: onboarding-json-parse
  file: backend/api/onboarding.py
  symbol: _extract_user_meta / _extract_json_block
  issue: >
    The model sometimes returns JSON that json.loads cannot parse (trailing
    prose, code fences, truncation at the 8k/24k max_tokens cap). _extract_json_block
    returning None or a JSONDecodeError silently drops a completed profile.
  fix: >
    Tolerant extraction (strip fences, take the largest balanced-brace span) and
    log the raw block on parse failure so completion is not silently lost.
  test: >
    Unit test extraction against fenced JSON, trailing-prose JSON, and truncated
    JSON.
  confidence: medium

## Per-function annex

**onboarding** (`sarathi-onboarding`) — tier A-conditional: synchronous
double-role stage machine that calls Bedrock with `max_tokens` up to 24000. Two
known classes: history ending on an assistant message (Bedrock 400) and
JSON-parse failures on the completion payload. See `onboarding-history-order`,
`onboarding-json-parse`. Both are currently confidence:medium, so they do not
clear the A gate on their own — propose them for a human, do not auto-implement
until a candidate is promoted to high. Errors here also tend to trip
`sarathi-lambda-slow-onboarding` and `sarathi-api-latency` (long generation near
the 29s timeout).

**settings** (`sarathi-settings`) — tier A-conditional: writes to workspace and
feed-card metadata. This is the most likely place the latent
`update_feed_card_meta` null-value bug surfaces in production (clearing a field
passes None). Route a `ValidationException` here to `feed-card-meta-null`
(confidence:high) — the one settings fault that clears the A gate: implement,
test, open a CR. Anything else stays B/report.

**chat-stream** (`sarathi-chat-stream`) — tier A-conditional: async streamer.
Two classes: `KeyError` on a malformed dispatch payload (`chat-stream-keyerror`,
confidence:high -> qualifies for A), and hung streams when `APPSYNC_ENDPOINT` is
empty (the SigV4 request targets ""), which surfaces as
`sarathi-chat-chunks-not-delivered` more than as a Lambda error. The empty env
var is a `[manual]` config fix (B), not a code fix.

**pre-signup** (`sarathi-pre-signup`) — tier C (human-only, never auto-touch):
the Cognito pre-sign-up trigger. This is on the auth/security path — a bad fix
here blocks ALL login/signup, so its blast radius is too large for any
autonomous change. An error here blocks new user registration entirely, so treat
it as higher urgency than a generic sev3, but the agent stops immediately and
pages a human; it takes no automated action and opens no branch or CR. Failures
are usually a validation/allowlist rule raising on an input it should reject
cleanly, or a DynamoDB error on the dedupe check. A human confirms whether it is
correctly rejecting a disallowed signup (working as intended) or erroring on a
valid one before any change.

## Escalation

If the erroring function is `pre-signup` (signups blocked) or an `api-*`/`chat`
function with a co-firing `sarathi-api-5xx` (users broadly affected), raise to
sev2. A single pipeline-step error that re-drives cleanly stays sev3. Persistent
Bedrock/DynamoDB throttling escalates via the dependency runbooks.

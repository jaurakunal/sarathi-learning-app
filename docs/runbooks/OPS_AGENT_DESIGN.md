# Sārathi Ops Agent: incident-to-branch design

This describes how an ops agent turns a Sārathi alarm into a diagnosed incident
and, when the fault is a known code bug, a review-ready fix on a feature branch.
The design point I care about most is the gate: the agent does the tedious,
error-prone first hour of an incident (find the runbook, run the read-only
diagnostics, localize the fault, draft the fix with a test), and a human still
owns every irreversible action. Nothing the agent does on its own touches
mainline or production.

## Current state

Sārathi has 39 CloudWatch alarms wired to the `sarathi-alarms` SNS topic, which
AWS Chatbot posts into Slack. Today the loop after that is entirely manual: a
human sees the Slack message, opens the console, remembers (or rediscovers)
which log group and which state machine to look at, runs the diagnostic commands
by hand, and only then starts thinking about a fix. The failure classes repeat.
Bedrock throttling, the latent `update_feed_card_meta` null-value bug, onboarding
message-history ordering, an empty `APPSYNC_ENDPOINT` hanging chat streams. The
same commands get typed against the same log groups every time. The runbooks in
this folder capture that repeated knowledge in a form both a human and an agent
can follow, and the agent exists to run the deterministic part of it fast.

## What the agent does

Given an incident (at minimum an alarm name, optionally debug metadata like an
execution ARN, a user id, or a time window), the agent routes the alarm through
the `README.md` routing table to exactly one runbook, parses that runbook by the
contract documented there, and runs the read-only commands in the `Diagnostics`
section with the placeholders filled from the incident payload. It reads the
output, matches it against the ordered `Likely Causes`, and decides whether a
`Code Fix Candidate` with `confidence: high` applies. When one does, it creates
a fresh feature branch, implements that specific fix, writes the test named in
the candidate, runs the build and tests locally, pushes the branch, and posts a
summary to the human with the branch name, the diagnosis, and the proposed
change. When no high-confidence code fix applies, or the remediation step is
tagged `[manual]`, it stops after diagnostics and posts findings for a human to
act on. It never merges and never deploys.

## Remediation tiering and the CR-not-deploy stance

Not every alarm deserves the same amount of autonomy, so each runbook now carries
an `auto_remediation` tier in its frontmatter that says how far the agent may act
once it has diagnosed the fault. Tier A is for a root cause that is a
deterministic code or config bug the agent can fix: it branches, implements the
fix, runs the unit tests and the integration tests (`make test`, `make api-test`,
`make integration-test`), and if they pass it opens a CR for a human to review.
Tier A is usually conditional, gated on the diagnosed fault mapping to a
`Code Fix Candidate` marked `confidence: high`; when that condition is not met the
agent drops to tier-B behavior and only reports. Tier B is for a root cause that
is capacity, an external dependency, or data (a Bedrock throttle, a DynamoDB hot
partition, a source drought, an empty config value), where there is nothing to
fix in code, so the agent runs the read-only diagnostics and posts its findings
and likely cause. Tier C is for the auth, security, and IAM blast-radius cases,
the clearest being the Cognito `pre-signup` trigger where a wrong fix would block
every login and signup; here the agent takes no automated action at all and pages
a human immediately.

The line I care about most in this tiering is that tier A stops at a CR.
Auto-deploy is explicitly out of scope. The most autonomous thing the agent ever
does is open a code review with a passing test attached, and a human still reads
it, approves it, and lets it flow to production through the normal CDK deploy
path. This holds even when the fix would widen an IAM permission on a
least-privilege role (adding a DynamoDB or AppSync action, for example): the
change can be written and reviewed, but it is never deployed by the agent.
Opening the CR is the handoff, not the finish line, and keeping the irreversible
step (the merge and the deploy) with a person is the whole point of the design.

## Incident-to-agent trigger wiring

For v1 the trigger is manual. A human (or the main Claude session) invokes the
`sarathi-ops` agent with the alarm name and any metadata pulled from the Slack
alarm message. This keeps a person in the loop at the very first step, which is
the right amount of caution while the agent's judgment is still being trusted.

The intended future wiring, out of scope for this build, adds an automated
bridge on the front. The `sarathi-alarms` SNS topic gains a second subscriber
alongside AWS Chatbot: either an EventBridge rule on the CloudWatch alarm state
change, or a Lambda subscribed directly to the topic. That Lambda normalizes the
alarm payload (alarm name, state, timestamp, and any dimensions) into the
incident shape the agent expects and hands it to an agent runtime. Even in that
future, the human-in-the-loop gate does not move: the automated bridge only gets
the agent to the point of a pushed branch and a notification. The diagram below
shows both the v1 path and the future bridge.

```
  CloudWatch alarm  ->  SNS: sarathi-alarms  ->  AWS Chatbot  ->  Slack  ->  [human]
                                            \
                                             \  (FUTURE, out of scope)
                                              -> EventBridge / SNS-subscribed Lambda
                                                    -> normalize to incident payload
                                                        -> sarathi-ops agent
  [human] --(v1: manual invoke with alarm name + metadata)--------> sarathi-ops agent

  sarathi-ops agent:
     route -> parse runbook -> run read-only diagnostics -> match cause
        -> high-confidence code fix?
             yes -> new feature branch + fix + test + build + push -> notify human
             no / [manual] -> post findings -> notify human
                                                    |
                                          [human reviews, merges, deploys]
```

## Guardrails

The guardrails are the point of the design, not an afterthought, so they are
enforced in three places: the agent's own instructions, the tools it is granted,
and the runbook contract it reads from.

**Branch-only, CR for review, human merge.** For a tier-A fix the agent creates a
branch named `ops/<alarm>-<yyyymmdd>-<short>` off the current default branch,
commits the fix and test there, pushes it, and opens a CR for a human to review.
It is explicitly forbidden from merging that CR, from checking out or committing
to `mainline`, and from running any deploy (`cdk deploy`, pipeline promotion, or
equivalent). The current repo default branch is `mainline`, so any attempt to
commit there is a hard stop. Opening the CR is as far as the autonomy goes; the
human approves it and the deploy happens through the normal CDK path.

**No production mutation.** Everything in a runbook's `Diagnostics` section is
read-only by construction (the parsing contract requires it), so the agent may
run all of them without asking. Anything that mutates AWS state (re-driving a
pipeline execution, changing capacity, editing an env var, restoring an IAM
grant) is tagged `[manual]` in the runbook and is never executed by the agent.
It surfaces those steps in its summary as recommended human actions. This
matches the standing rule that all AWS changes go through CDK, not the console
or ad-hoc CLI.

**Confidence gate on code fixes.** The agent acts autonomously only on
`Code Fix Candidates` marked `confidence: high` (today: the latent
`update_feed_card_meta` null-value fix, the `chat_stream` KeyError guard, the
`APPSYNC_ENDPOINT` empty-endpoint guard, and the `chat_dispatch` return-shape and
retry fix). Medium and low confidence candidates are described in the summary as
proposals for a human to confirm before the agent writes them. This keeps the
autonomous surface to changes that are small, well-understood, and covered by a
test.

**Tests are not optional.** A branch is not review-ready without a passing test.
Every high-confidence candidate names the test to write. The agent runs the
build and the tests locally before pushing, and if they do not pass it does not
push a broken branch; it posts what it found instead.

## Open questions

- **Idempotency and dedup.** If the future SNS bridge fires the agent twice for
  the same alarm (state flap, or the OK action re-firing), how does the agent
  avoid opening two branches for one incident? A dedup key on alarm name plus a
  time bucket is the likely answer, but it needs a store.
- **Concurrent incidents.** When several alarms fire together (a Bedrock throttle
  lighting up feed-stale, pipeline-failed, and llm-failures at once), should the
  agent correlate them into one investigation or handle each independently?
  The runbooks cross-reference each other, which helps, but the orchestration is
  undecided.
- **Branch hygiene.** Ops branches that a human decides against will accumulate.
  Who prunes them, and after how long?
- **Diagnostic credential scope.** The agent needs read-only AWS access
  (CloudWatch, Logs, Step Functions describe, Lambda get-config, DynamoDB
  describe). That credential must be least-privilege and must not carry any
  mutating permission, so that even a prompt-injected agent cannot change
  production. Scoping and issuing that role is out of scope here.
- **Notification target.** v1 posts a summary back to whoever invoked it. The
  future bridge needs a fixed channel (a Slack thread on the original alarm
  message is the natural choice) and a decision on how much of the diff to inline.

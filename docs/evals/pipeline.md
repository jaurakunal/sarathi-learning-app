# Sarathi LLM Evaluation Pipeline

A reusable harness for comparing alternative LLMs against the Sonnet 4.6
baseline on the digest task. Uses your own real engagement (read,
bookmarked, dismissed) as the golden signal — no synthetic ground truth.

## Why this exists

Before swapping the digest model (e.g., to GLM-5, Kimi K2.5, or Haiku 4.5)
to save cost, we want evidence that the alternative produces feed cards
that are at least as good as Sonnet's. "Good" here means:

- Hooks/digests that connect to **your** research interests
- Calibrated to **your** level (math route-around, applied lead)
- Predictive of how **you** would actually engage

## What the pipeline does

```
setup    →  clone profile + build golden dataset from live user
run      →  generate cards for the eval set with model X
judge    →  LLM-as-judge scores candidate vs golden + checks engagement alignment
report   →  print comparison table across all completed runs
reset    →  wipe test user paper data (keep profile)
```

DDB layout (extends `backend.shared.db`):

| PK                          | SK             | Purpose                                       |
|-----------------------------|----------------|-----------------------------------------------|
| `EVAL#DATASET`              | `META`         | dataset metadata (paper count, last built)    |
| `EVAL#DATASET`              | `PAPER#<id>`   | paper + golden card + engagement summary      |
| `EVAL#RUN#<run_id>`         | `META`         | run summary (model, cost, latency, success)   |
| `EVAL#RUN#<run_id>`         | `PAPER#<id>`   | candidate card + per-paper cost/timing        |
| `EVAL#JUDGE#<judge_run_id>` | `META`         | judge run summary (means, alignment %)        |
| `EVAL#JUDGE#<judge_run_id>` | `PAPER#<id>`   | per-paper scores + winner + raw response      |

## Prerequisites

- AWS credentials with read access to live user data and write access on the test user
- `AWS_PROFILE=poc` (or whatever profile points at the Sarathi POC account)
- The test user must NOT have manual paper data you care about — `setup` and
  `run --reset-first` will wipe it.

## End-to-end run

```bash
# 1. Build the golden dataset (idempotent — safe to re-run).
AWS_PROFILE=poc python scripts/eval_pipeline.py setup

# 2. (Optional but recommended) Validate the judge prompt itself.
#    Should print engagement_alignment_pct >= 70%.
AWS_PROFILE=poc python scripts/eval_pipeline.py judge --self-validate

# 3. Run digest with the baseline (Sonnet) — gives us a reference point.
AWS_PROFILE=poc python scripts/eval_pipeline.py run \
    --model us.anthropic.claude-sonnet-4-6

# 4. Run digest with a candidate model.
AWS_PROFILE=poc python scripts/eval_pipeline.py run \
    --model us.anthropic.claude-haiku-4-5

# 5. Judge each candidate run. Use the run_id printed by step 3/4.
AWS_PROFILE=poc python scripts/eval_pipeline.py judge \
    --candidate <run_id_from_step_4>

# 6. Print the comparison table.
AWS_PROFILE=poc python scripts/eval_pipeline.py report
```

## Adding a new model to test

1. Confirm Bedrock access to the model in `us-east-1`.
2. Add an entry to `PRICING_PER_1K` in `backend/eval/runner.py` so cost
   shows up in the report. (Without it, the runner falls back to a default
   estimate.)
3. `python scripts/eval_pipeline.py run --model <bedrock_model_id>`.
4. `python scripts/eval_pipeline.py judge --candidate <run_id>`.
5. `python scripts/eval_pipeline.py report`.

## Interpreting the report

| Column                  | What it measures                                                    |
|-------------------------|---------------------------------------------------------------------|
| Relev.                  | Mean (1-5): does the hook connect to user's research interests?     |
| Specif.                 | Mean (1-5): is it about THIS paper's actual contribution?           |
| Calib.                  | Mean (1-5): does it match the user's level (math route-around)?     |
| Action.                 | Mean (1-5): does it surface "why now" / next steps?                 |
| Eng. Align %            | % of papers where judge's predicted engagement matched actual.      |
| Win Rate %              | % of papers where the judge picked candidate over golden.           |
| $/paper                 | Average Bedrock cost per paper (approximate — uses local pricing).  |
| Latency ms              | Mean per-paper latency, including S3 + LLM round-trip.              |

A candidate model is a credible drop-in replacement when:

- Eng. Align % is within 5 pts of golden's self-validation alignment
- Win Rate is at least ~40% (golden is a strong baseline; ties count)
- Specificity and Calibration scores aren't lower than golden's
- $/paper is materially cheaper

If only Relevance and Actionability hold up but Calibration drops, the
model probably defaults to a more generic register and would push the
user back toward textbook-style explanations they already opted out of.

## Bias mitigation in the judge

- Cards are anonymized: leading "Here's a digest:" / "I'll provide:" /
  "Sure!" phrases are stripped before the judge sees them.
- A/B order is randomized per paper (seeded RNG so judge runs are
  reproducible). Winner is "un-swapped" before persistence.
- Self-validation: judging golden vs golden should produce engagement
  alignment >70% — if it doesn't, the judge prompt itself is unreliable
  and the candidate scores should be discarded until it's tightened.

## Cost notes

- `setup` makes **zero** LLM calls. Just DDB read/writes.
- `run --model X` makes one LLM call per paper in the dataset.
- `judge` makes one LLM call per (paper × candidate run).
- `judge --self-validate` makes one LLM call per paper (golden vs golden).
- `report` is read-only.

For a 30-paper dataset:
- Sonnet 4.6 run: ~$0.30 - $0.50
- Haiku 4.5 run: ~$0.05
- Judge with Sonnet: ~$0.30
- Self-validation: ~$0.30 (one-time)

## Resetting between runs

`run` calls `reset` first by default (controlled via `--reset-first`,
defaults to true). The reset wipes:

- Test user feed cards
- Test user paper records and library entries
- Test user engagement events

It deliberately preserves:

- Profile (META + areas + hypothesis)
- Conversations and pinned chat insights
- Push subscriptions

To clean the test user without running anything:

```bash
AWS_PROFILE=poc python scripts/eval_pipeline.py reset
```

## Files

- `scripts/eval_pipeline.py` — CLI entry point.
- `backend/eval/dataset.py` — clone profile + build/load eval dataset.
- `backend/eval/runner.py` — execute candidate runs with cost/timing tracking.
- `backend/eval/judge.py` — LLM-as-judge with anonymization + alignment.
- `backend/eval/report.py` — comparison table rendering.
- `tests/eval/` — unit tests covering all of the above.

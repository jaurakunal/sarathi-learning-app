# Sārathi LLM Eval — Baseline (Claude Sonnet 4.6)

_Generated: 2026-06-26_

## Setup

- **Eval dataset**: 18 papers from live user (kunaljaura@gmail.com), real engagement signals
  - 6 read, 3 bookmarked, 1 dismissed, 8 none
  - 5 papers with golden cards (the rest were digested but never surfaced as feed cards)
- **Test user**: kunal@example.com (`447844a8-c0e1-700b-2fdf-f9512eee3e49`)
- **Profile cloned** from live user before run
- **Token counts**: real Bedrock-reported (`input_tokens` / `output_tokens`)
- **Pricing**: published Bedrock on-demand rates (verified 2026-06-26)
  - Sonnet 4.6: $3.00 / $15.00 per 1M tokens

## Methodology

1. Reset test user paper data
2. Run digest pipeline on each paper with the model under test
3. LLM-as-judge (Sonnet 4.6) compares each candidate card against the
   original golden card stored on the live user
4. Judge scores 1-5 on 4 dimensions, picks a winner per paper
5. Aggregate across all valid (golden + candidate) papers

## Results

| Metric | Value |
|---|---|
| Papers succeeded | **18 / 18** |
| Avg Relevance | **4.80 / 5** |
| Avg Specificity | **4.80 / 5** |
| Avg Calibration | **4.80 / 5** |
| Avg Actionability | **4.80 / 5** |
| Win rate vs golden cards | **80%** |
| Avg cost per paper | **$0.1045** |
| Avg latency per paper | **~70 seconds** |

## Score interpretation

- **Relevance** — does the hook connect to the user's research interests / frontiers?
- **Specificity** — is it about THIS paper's actual contribution, not generic-sounding?
- **Calibration** — does the explanation match the user's level (math route-around, applied lead)?
- **Actionability** — does it surface "why now" / what to do with this?
- **Win rate** — fraction of head-to-head paper comparisons where the new candidate card "won"
  against the original golden card. 80% means Sonnet-on-fresh-context typically produces equally
  good or better cards than the original Sonnet output, suggesting prompt evolution since the
  golden cards were generated.

## Cost basis

Per active user with ~30 papers/day digested:
- Daily: ~$3.13
- Monthly: ~$94

This was confirmed against actual AWS Cost Explorer data:
- June 1-25 Bedrock spend: $34.24 (1-2 active users)
- ~$1/day per heavy active user

## Engagement alignment

- **0%** — judge engagement predictions don't correlate with actual user engagement.
- This is expected: engagement depends on factors not present in card content
  (mood, schedule, what else the user read that week). Judge is reading cards in
  isolation. We rely on the dimensional scores + win rate as quality proxies.

## What this baseline means

- **4.80 across all four dimensions** is the floor for quality. Anything noticeably below
  this (e.g., <4.0) is a measurable regression.
- **$0.1045/paper** is the cost basis. Any candidate model that costs more than this isn't
  worth considering. Targets for cost savings should be at least 50% reduction.
- **80% win rate** is what we expect from a model that produces cards on par with the
  baseline. Significantly lower win rate (<50%) means the model is consistently producing
  worse cards even when dimensional scores look ok.

## Run metadata

- Run ID: `2026-06-26T18:18:09.000Z` (run 6 in eval history)
- Judge model: `us.anthropic.claude-sonnet-4-6`
- Generated report: `sarathi_eval_us-anthropic-claude-sonnet-4-6_20260626_182033.md`

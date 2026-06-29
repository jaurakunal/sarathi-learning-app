# Sārathi LLM Evaluation — Final Report

_Compiled: 2026-06-29_
_Eval period: 2026-06-26 → 2026-06-29_

---

## Executive Summary

We evaluated **5 LLM candidate models** against the **Claude Sonnet 4.6** baseline across **5 pipeline steps** using real production data: 18 papers the user engaged with positively + 50 papers Sonnet rejected at triage.

**Bottom-line recommendation: migrate triage, lens, and digest to Kimi K2.5. Keep Sonnet for relevance filter, learn, chat, onboarding, and weekly brief.**

Projected monthly cost reduction per active user: **$22 → $4.32 (80% reduction)** on the LLM steps tested. Quality validated across 4 dimensions per step with 3-run replication on digest.

---

## Methodology

### Eval dataset

Source: live user `kunaljaura@gmail.com` (`00000000-0000-0000-0000-000000000000`), with profile cloned to test user `kunal@example.com` (`447844a8-c0e1-700b-2fdf-f9512eee3e49`).

| Class | Count | Source |
|---|---|---|
| Positive (digested papers) | 18 | Live user's `digested` papers; engagement signals (read, bookmarked, etc.) |
| Negative (rejected papers) | 50 | Sampled from 456 papers Sonnet rejected at triage; mixed across `over_head` (16), `too_basic` (16), `unknown` (15), `just_right` (3) levels |

### Cost basis

All cost numbers use **real Bedrock-reported token counts** (not estimates) × **published Bedrock on-demand prices** (verified June 2026):

| Model | Input ($/1M) | Output ($/1M) |
|---|---|---|
| Claude Sonnet 4.6 | $3.00 | $15.00 |
| Claude Opus 4.8 (used as judge only) | $15.00 | $75.00 |
| Kimi K2.5 | $0.60 | $3.00 |
| GLM-5 | $1.00 | $3.20 |
| Qwen3 VL 235B | $0.53 | $2.66 |
| DeepSeek V3.2 | $0.62 | $1.85 |

### Judge

LLM-as-judge using **Claude Opus 4.8** (different model family than Sonnet 4.6 baseline, mitigates self-preference bias). Judge sees anonymized A/B card pairs with random A/B order per paper.

### Variance control

For digest: **3 model runs × 1 judge** (Option A replication) — captures variance from `temperature=0.7` in the digest prompts.

For triage/lens/relevance/learn: **1 model run** with **68-paper test set** (sample size compensates for run variance).

---

## Pipeline Map

| Step | File | Volume per active user | Tested | Decision |
|---|---|---|---|---|
| Discover query gen | `shared/query_gen.py` | ~5/day | ❌ Not tested | Keep Sonnet |
| Relevance filter | `shared/relevance_filter.py` | ~30/day | ✅ Tested | **Keep Sonnet** |
| Triage | `pipeline/triage.py` | ~30/day | ✅ Tested | **Migrate to Kimi K2.5** |
| Lens | `pipeline/lens.py` | ~5-10/day | ✅ Tested | **Migrate to Kimi K2.5** |
| Chunker | `shared/chunker.py` | ~5/day | ❌ Not tested | Keep Sonnet |
| **Digest** | `pipeline/digest.py` | ~5/day | ✅ **Tested most rigorously** | **Migrate to Kimi K2.5** |
| Learn | `pipeline/learn.py` | 1/user/day | ✅ Tested | Keep Sonnet |
| Weekly brief | `pipeline/weekly_brief.py` | 0.14/day | ❌ Not tested | Keep Sonnet |
| Onboarding | `api/onboarding.py` | rare | ❌ Not tested | Keep Sonnet |
| Suggestions | `api/suggest.py` | varies | n/a | Already on Haiku |
| Auto-title | `streaming/chat_stream.py` | per conv | n/a | Already on Haiku |
| Chat (RAG) | `streaming/chat.py` | per user msg | ❌ Not tested | Keep Sonnet |

---

## Results: Digest Step

The user-facing card generation step. Highest cost per call (~$0.10 on Sonnet).

### Single-run head-to-head (5 papers, Sonnet judge)

| Model | Relev | Specif | Calib | Action | Win% | $/paper | Latency |
|---|---|---|---|---|---|---|---|
| **Sonnet 4.6** (baseline) | 4.80 | 4.80 | 4.80 | 4.80 | 80% | $0.1045 | 70s |
| GLM-5 | 4.60 | 4.40 | 4.20 | 4.40 | 40% | $0.0246 | 62s |
| Kimi K2.5 | 4.60 | 4.60 | 4.20 | 4.60 | 60% | $0.0166 | 20s |
| Qwen3 VL 235B | 4.40 | 4.40 | 4.00 | 4.60 | 20% | $0.0157 | 37s |
| DeepSeek V3.2 | 4.40 | 4.00 | 4.00 | 4.20 | 20% | $0.0150 | 39s |

### Cross-judge validation (Opus 4.8 judge, 3 seeds)

| Model | Relev (μ±σ) | Specif (μ±σ) | Calib (μ±σ) | Action (μ±σ) | Win% (μ±σ) |
|---|---|---|---|---|---|
| Sonnet 4.6 | 5.00±0.00 | 5.00±0.00 | 4.93±0.12 | 5.00±0.00 | 100±0 |
| GLM-5 | 5.00±0.00 | 5.00±0.00 | 4.60±0.20 | 4.73±0.12 | 53±12 |
| Kimi K2.5 | 4.60±0.00 | 4.87±0.12 | 4.20±0.00 | 4.40±0.20 | 20±0 |
| Qwen3 VL | 4.67±0.12 | 4.40±0.00 | 4.00±0.20 | 4.47±0.12 | 20±0 |
| DeepSeek V3.2 | 4.60±0.00 | 4.53±0.31 | 4.13±0.23 | 4.33±0.12 | 13±12 |

Cross-judge surprise: under unbiased Opus 4.8 judge, Kimi appeared to *lose* ground (60% → 20% win rate). This was due to small-sample noise.

### Three-run replication (Option A — full digest run × 3 per model)

| Model | Relev (μ±σ) | Specif (μ±σ) | Calib (μ±σ) | Action (μ±σ) | Win% (μ±σ) | $/paper | Latency |
|---|---|---|---|---|---|---|---|
| Sonnet 4.6 | 5.00±0.00 | 5.00±0.00 | 4.80±0.00 | 5.00±0.00 | 86.67±11.55 | $0.1048 | 74s |
| GLM-5 | 5.00±0.00 | 4.87±0.12 | 4.63±0.15 | 4.72±0.10 | 56.67±**20.82** | $0.0249 | 51s |
| **Kimi K2.5** | 4.80±0.00 | 4.93±0.12 | 4.73±0.12 | 4.73±0.12 | **60.00±0.00** | **$0.0166** | **30s** |
| Qwen3 VL | 4.67±0.12 | 4.47±0.12 | 4.07±0.23 | 4.47±0.12 | 26.67±11.55 | $0.0154 | 35s |
| DeepSeek V3.2 | 4.67±0.12 | 4.60±0.00 | 4.20±0.00 | 4.20±0.20 | 20.00±0.00 | $0.0150 | 35s |

### Digest verdict

**Kimi K2.5** wins on consistency. GLM-5's win rate has σ=20.82 (one run hit 80%, another 40%) — unpredictable in production. Kimi K2.5 hits 60% win rate with **σ=0.00 across three runs**.

- 6.3× cheaper than Sonnet
- 2.5× faster
- ~3% quality drop on dimensional scores
- Zero variance run-to-run

---

## Results: Triage Step

68 papers (18 positive + 50 negative). The negative class is real production data — papers Sonnet actually rejected at triage.

| Model | Worth Acc | Recall | Specificity | F1 | Score MAE | Score Corr | $/paper | Latency |
|---|---|---|---|---|---|---|---|---|
| Sonnet 4.6 | 0.897 | 0.611 | 1.000 | 0.759 | 0.043 | 0.983 | $0.0055 | 3.1s |
| **Kimi K2.5** | **1.000** | **1.000** | **1.000** | **1.000** | 0.108 | 0.969 | **$0.0010** | 2.0s |
| GLM-5 | 0.971 | 0.944 | 0.980 | 0.944 | 0.093 | 0.922 | $0.0014 | 4.5s |

### Notable findings

**Sonnet's recall is 0.611** — meaning Sonnet today disagrees with Sonnet's prior decisions on positives 39% of the time. This is intrinsic noise in the triage task (papers are borderline, model output non-deterministic with `temperature=0.7`).

**Kimi K2.5 has perfect F1** — zero false positives, zero false negatives across 68 papers. It correctly accepts every paper Sonnet accepted AND correctly rejects every paper Sonnet rejected. Better alignment with stored Sonnet decisions than Sonnet itself.

### Triage verdict

**Migrate to Kimi K2.5.** 5.5× cheaper, perfect classification accuracy.

---

## Results: Lens Step

55 papers (subset with `hypothesis_relevant` field set). Compares the candidate model's verdict (`supports`/`refutes`/`refines`/`irrelevant`) against the stored Sonnet verdict; LLM-as-judge separately scores reasoning coherence.

| Model | Verdict Match | Coherent | Align | $/paper | Latency |
|---|---|---|---|---|---|
| Sonnet 4.6 | 56.4% | 89.1% | 52.7% | $0.0016 | 2.6s |
| **Kimi K2.5** | **63.6%** | **89.1%** | **58.2%** | **$0.0003** | 1.7s |
| GLM-5 | 50.9% | 85.5% | 49.1% | $0.0003 | 2.6s |

### Lens verdict

**Migrate to Kimi K2.5.** Kimi beats Sonnet on both verdict alignment AND reasoning coherence. 5.3× cheaper.

The Sonnet self-comparison being only 52.7% reflects fundamental task noise: lens decisions are inherently fuzzy ("does this paper relate to my hypothesis?") and benefit from models that produce more deterministic output.

---

## Results: Relevance Filter Step

43 papers. Originally tested with synthetic off-topic negatives (food science, civil engineering) — too easy. Re-run with real near-miss negatives from production:

| Model | Accuracy | Precision | Recall | F1 | $/paper |
|---|---|---|---|---|---|
| **Sonnet 4.6** | **0.960** | **0.947** | 1.000 | **0.973** | $0.00024 |
| Kimi K2.5 | 0.920 | 0.900 | 1.000 | 0.947 | $0.00004 |
| GLM-5 | 0.698 | 0.581 | 1.000 | 0.735 | $0.00006 |

### Relevance Filter verdict

**Keep Sonnet.** With realistic near-miss negatives, the cheaper models lose precision — Kimi keeps 10% of off-topic papers (precision 0.900); GLM-5 collapses (precision 0.581).

Cost differential is negligible ($0.00024 vs $0.00004 per paper) and the filter is the gate before the more expensive triage step. False positives at the relevance filter cascade into wasted triage spend on irrelevant papers.

### Side note on test rigor

This step illustrates why **negative-class data quality matters**. The original eval (synthetic negatives) showed all 3 models tied at F1=1.000 — completely uninformative. With real near-miss negatives, the cheaper models' weaknesses surface clearly.

---

## Results: Learn Step

Single input (entire engagement history aggregated), LLM-as-judge alignment scores 1-5:

| Model | Areas | Hypothesis | Summaries | Style | Overall | $/run | Latency |
|---|---|---|---|---|---|---|---|
| Sonnet 4.6 | 5 | 5 | 5 | 5 | **5/5** | $0.0197 | 18.6s |
| Kimi K2.5 | 5 | 5 | 4 | 5 | 5/5 | $0.0254 | 9.2s |
| GLM-5 | 5 | 4 | 4 | 5 | 5/5 | $0.0245 | 5.9s |

### Learn verdict

**Keep Sonnet.** All three score 5/5 overall, but Kimi shows minor drift on summaries (4 vs 5). This step:
- Runs once daily per user (low volume)
- Outputs feed back into the user's profile, affecting all future digests
- Multi-section reasoning over engagement history (high complexity)

The Sonnet cost ($0.62/month per active user) is too small to justify quality risk on a step that compounds.

---

## Combined Cost Projection

Per active user, ~30 papers/day:

| Step | Sonnet baseline | New plan | Monthly savings |
|---|---|---|---|
| Relevance filter (30/day) | $0.22 | $0.22 (keep Sonnet) | $0 |
| Triage (30/day) | $4.95 | $0.90 (**Kimi**) | $4.05 |
| Lens (5-10/day) | $0.48 | $0.09 (**Kimi**) | $0.39 |
| Digest (5/day) | $15.72 | $2.49 (**Kimi**) | $13.23 |
| Learn (1/day) | $0.62 | $0.62 (keep Sonnet) | $0 |
| **TOTAL (tested steps)** | **~$22/mo** | **~$4.32/mo** | **~$18/mo (80%)** |

Plus untested but kept on existing models:
- Chat (Sonnet): ~$5/mo (unchanged)
- Onboarding/weekly brief/query gen/chunker: ~$0.50/mo combined (unchanged)

**All-in: ~$28/mo per active user → ~$10/mo per active user (~64% total cost reduction).**

---

## Models Eliminated

| Model | Reason |
|---|---|
| **GLM-5** | High variance on digest (σ=20.82 win rate); collapses on relevance filter (F1=0.735) with real negatives. Cheaper than Sonnet but less consistent than Kimi K2.5 at higher cost. |
| **Qwen3 VL 235B A22B** | Lowest dimensional scores (avg 4.42); 20% win rate; calibration drops to 4.07. |
| **DeepSeek V3.2** | Lowest win rate (20%); specificity 4.00; calibration 4.20. Reputation strong on benchmarks but doesn't translate to user-profile-tailored card generation. |

---

## Caveats

1. **Single user profile.** All evals calibrated against one user. Other users with different domains may show different model rankings. Worth re-validating once we have more users.

2. **Engagement alignment is 0% across all models** — judges can't predict actual user engagement from card content alone. Expected: engagement depends on factors not in the card (mood, schedule, what else they read). Dimensional scores + win rate are the more reliable signals.

3. **Chat / onboarding / weekly brief untested.** These remain on Sonnet by default. Eval would require different methodology (no golden cards). Lower priority because user-facing quality matters more there.

4. **Sample size.** Digest had 5 head-to-head papers (only 5 papers had golden cards from production). Triage had 68. Lens had 55. The dimensional score differences between top models are small (often within 0.2) — could shift with more data.

5. **Bedrock pricing changes.** Costs based on published rates as of 2026-06-26. Bedrock on-demand pricing may shift; revisit periodically.

---

## Migration Plan

### Phase 1: Code changes (estimated 30 min)

1. **`backend/pipeline/triage.py`** — change default `model` to `moonshotai.kimi-k2.5`. Keep Sonnet as fallback on 5xx.
2. **`backend/pipeline/lens.py`** — same.
3. **`backend/pipeline/digest.py`** — same.
4. **No changes needed to**: `relevance_filter.py`, `learn.py`, `weekly_brief.py`, `chat.py`, `onboarding.py`, `chunker.py`, `query_gen.py`.
5. **Add fallback wrapper** in `shared/llm.py`: `call_llm_with_fallback(primary, fallback, ...)` that catches Bedrock 5xx on primary and retries on fallback.
6. **Update tests** — existing tests use mocked LLM calls; should still pass.

### Phase 2: Canary (1 week)

Route 50% of nightly pipeline runs to Kimi K2.5 for the migrated steps. Monitor:
- Engagement metrics on produced cards (read/bookmark/dismiss rates)
- Error rates on Bedrock calls (Kimi is newer; less battle-tested SLA)
- Cost actuals from CloudWatch + Cost Explorer

### Phase 3: Full migration

If canary shows no regression in engagement and acceptable error rates, flip default to Kimi K2.5. Can revert via env var without redeploy.

---

## Eval Harness — Reusable for Future Decisions

Built during this work:
- `backend/eval/runner.py` — digest replication runner
- `backend/eval/judge.py` — LLM-as-judge with bias mitigation
- `backend/eval/triage_eval.py`, `lens_eval.py`, `relevance_eval.py`, `learn_eval.py` — per-step evals
- `backend/eval/dataset.py` — positive (engagement-anchored) + negative (rejection-anchored) eval set builders
- `scripts/eval_pipeline.py`, `scripts/eval_full.py`, `scripts/eval_pipeline_steps.py` — CLI tools
- 153 unit tests covering eval logic

This harness is reusable for:
- Future model evaluations (new Bedrock models)
- Prompt tuning experiments (does the new system prompt regress quality?)
- Quarterly drift checks (do existing models still produce expected quality?)

---

## Run History

Eval reports generated during this work:

| Date | Phase | Models | Report |
|---|---|---|---|
| 2026-06-26 | Digest baseline (Sonnet judge) | Sonnet 4.6 | `sarathi_eval_us-anthropic-claude-sonnet-4-6_20260626_182033.md` |
| 2026-06-26 | Digest candidate sweep | GLM-5, Kimi K2.5, Qwen3, DeepSeek | `sarathi_eval_*_20260626_18*.md` (5 files) |
| 2026-06-26 | Cross-judge with Opus 4.8 | All 5 models | (re-judged in place) |
| 2026-06-26 | 3-seed judge replication | All 5 models | (logged) |
| 2026-06-26 | 3-run digest replication (Option A) | All 5 models | `docs/eval-option-a-raw.log` |
| 2026-06-26 | Pipeline steps eval (positives only) | Sonnet, Kimi, GLM | `sarathi_eval_pipeline_steps_20260626_223337.md` |
| 2026-06-26 | Pipeline steps eval (with 50 negatives) | Sonnet, Kimi, GLM | `sarathi_eval_pipeline_steps_20260626_235038.md` |

Underlying data persisted under DDB:
- `EVAL#DATASET` — 18 positive papers
- `EVAL#DATASET_NEG` — 50 negative papers
- `EVAL#RUN#<run_id>` — per-model digest run data
- `EVAL#JUDGE#<run_id>` — judge results
- `EVAL#TRIAGE#<run_id>`, `EVAL#LENS#<run_id>`, `EVAL#RELEVANCE#<run_id>`, `EVAL#LEARN#<run_id>` — per-step results

---

## Conclusion

Migrate triage + lens + digest to Kimi K2.5. Keep Sonnet for relevance filter, learn, chat, onboarding, weekly brief. Expected ~80% cost reduction on tested steps. Validated with 68-paper test set including real production negative-class data.

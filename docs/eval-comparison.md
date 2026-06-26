# Sārathi LLM Eval — Comparative Evaluation

_Updated: 2026-06-26_

This document tracks how candidate models compare against the Sonnet 4.6 baseline
on Sārathi's digest task. Baseline details: see `docs/eval-baseline-sonnet-4-6.md`.

## Summary table

| Model | Papers OK | Relev. | Specif. | Calib. | Action. | Win% vs golden | $/paper | Latency | $ vs Sonnet | Quality vs Sonnet |
|---|---|---|---|---|---|---|---|---|---|---|
| **Sonnet 4.6 (baseline)** | 18/18 | **4.80** | **4.80** | **4.80** | **4.80** | 80% | $0.1045 | 70s | 1.0× | 1.0× |
| GLM-5 | 15/18 | 4.80 | 4.60 | 4.40 | 4.60 | 40% | $0.0246 | 62s | 0.24× (4.2× cheaper) | -0.20 to -0.40 |
| **Kimi K2.5** | 17/18 | 4.60 | 4.60 | 4.20 | 4.60 | **60%** | $0.0166 | **20s** | 0.16× (6.3× cheaper) | -0.20 to -0.60 |
| Qwen3 VL 235B A22B | 18/18 | 4.40 | 4.40 | 4.00 | 4.60 | 20% | $0.0157 | 37s | 0.15× (6.7× cheaper) | -0.20 to -0.80 |
| DeepSeek V3.2 | 18/18 | 4.40 | 4.00 | 4.00 | 4.20 | 20% | **$0.0150** | 39s | **0.14×** (7.0× cheaper) | -0.40 to -0.80 |

## Cost basis (per active user, ~30 papers/day)

| Model | Daily | Monthly |
|---|---|---|
| Sonnet 4.6 | $3.13 | ~$94 |
| GLM-5 | $0.74 | ~$22 |
| Kimi K2.5 | $0.50 | ~$15 |
| Qwen3 VL 235B | $0.47 | ~$14 |
| DeepSeek V3.2 | $0.45 | ~$13.50 |

## Quality dimension comparison

| Dimension | Sonnet | GLM-5 | Kimi K2.5 | Qwen3 VL | DeepSeek V3.2 | Notes |
|---|---|---|---|---|---|---|
| Relevance | 4.80 | 4.80 ✓ | 4.60 | 4.40 | 4.40 | All within range |
| Specificity | 4.80 | 4.60 | 4.60 | 4.40 | **4.00** | DeepSeek weakest — drifts most generic |
| **Calibration** | **4.80** | 4.40 | 4.20 | 4.00 | 4.00 | Consistent weak spot across all candidates |
| Actionability | 4.80 | 4.60 | 4.60 | 4.60 | 4.20 | DeepSeek slightly weaker |

**Calibration is the differentiator.** Sonnet is consistently better at matching the user's
math comfort and applied bias. Cheaper models drift toward generic explanations.

## Win-rate ranking

Higher = produces cards that "win" against the original Sonnet golden cards more often.

1. **Sonnet 4.6**: 80% (re-running on same papers, fresh context)
2. **Kimi K2.5**: 60% — most competitive against Sonnet's golden cards
3. **GLM-5**: 40%
4. **Qwen3 VL**: 20% — consistently loses head-to-head despite reasonable dimension scores
5. **DeepSeek V3.2**: 20% — same head-to-head loss rate, lowest scores overall

## Speed

| Model | Avg latency / paper |
|---|---|
| Kimi K2.5 | **20s** — fastest |
| Qwen3 VL | 37s |
| DeepSeek V3.2 | 39s |
| GLM-5 | 62s |
| Sonnet 4.6 | 70s |

## Strategic interpretation

### Per-tier recommendation

| Decision | Best fit | Reasoning |
|---|---|---|
| **Replace Sonnet entirely on digest** | Kimi K2.5 | Best win rate (60%), fastest (20s), 6.3× cheaper. Calibration drop is real but acceptable. |
| **Cheapest possible** | Qwen3 VL | $0.0157/paper, but 20% win rate and 4.0 calibration is a real quality regression. Risky for primary digest. |
| **Quality-first** | Sonnet 4.6 | Stay on baseline. Justifies $39+ pricing. |
| **Hybrid (best for casual users)** | Kimi K2.5 for digest, Sonnet for chat | Captures most cost savings while keeping user-facing chat quality at baseline. |

### Cost vs quality frontier

```
Quality (avg of 4 dimensions, lower = worse)
4.80 ┤ ●  Sonnet 4.6
     │
4.65 ┤    ● GLM-5
     │
4.50 ┤        ● Kimi K2.5
     │
4.35 ┤              ● Qwen3 VL
     │
4.20 ┤                  ● DeepSeek V3.2
     │
4.00 ┴─┬───────┬───────┬───────┬───────┬─── Cost ($/paper)
       $0.10  $0.05   $0.025  $0.017  $0.015
```

**Sweet spot: Kimi K2.5.** Below the diminishing-returns elbow — moving from Sonnet to Kimi
saves 84% on cost for ~0.3 quality drop. Moving further (Qwen3, DeepSeek) saves only ~$0.001
more per paper but drops quality 0.4-0.6 more. Not worth it.

DeepSeek V3.2's reputation for strong quality (especially on coding/reasoning benchmarks)
doesn't translate well to this task. Specificity 4.00 and Calibration 4.00 are the weakest
dimensional scores in the candidate set — DeepSeek tends to produce generic explanations
rather than paper-specific or user-calibrated framing.

### Pricing implications

If we migrate digest to **Kimi K2.5**:

| Tier | Price | New cost | Margin |
|---|---|---|---|
| Standard | $9/mo | ~$3 (digest) + $1 (other LLM) + $1 (infra) = $5 | $4 (44%) |
| Pro | $19/mo | ~$5 (digest) + $3 (chat at Sonnet) + $1 (other) + $1 (infra) = $10 | $9 (47%) |
| Team | $49/mo | ~$8 + $5 + $2 + $1 = $16 | $33 (67%) |

This is real SaaS economics — sustainable margins at all tiers.

If we keep **Sonnet on everything**: only the Team tier ($49) has positive margin.

## Caveats

1. **5 valid head-to-head papers** — small sample. Win rates have noise of ±15% with this sample size.
2. **Self-judging bias** — Sonnet judges Sonnet's golden cards. Anonymization + A/B order randomization mitigates but doesn't eliminate. **See Opus 4.8 judge re-rating below for an unbiased view.**
3. **Engagement alignment is 0% across all models** — judge can't predict actual user engagement from card content alone. Dimensional scores + win rate are the more reliable signals.
4. **Single user profile** — these results are calibrated against one user (kunaljaura@gmail.com). Other users with different domains may see different rankings.

## Cross-judge comparison: Opus 4.8 as judge

To check for self-preference bias (Sonnet judging Sonnet-generated cards), we re-judged
all 5 candidate runs using **Claude Opus 4.8** (a more capable, different-instance model)
as the judge.

| Model | Judge: Sonnet 4.6 (avg) | Judge: Opus 4.8 (avg) | Δ |
|---|---|---|---|
| Sonnet 4.6 (vs golden) | 4.80 | **5.00** (perfect) | +0.20 |
| GLM-5 | 4.60 | **4.90** | +0.30 |
| Kimi K2.5 | 4.50 | 4.50 | 0.00 |
| Qwen3 VL | 4.35 | 4.35 | 0.00 |
| DeepSeek V3.2 | 4.55 | 4.55 | 0.00 |

| Model | Win% (Sonnet judge) | Win% (Opus 4.8 judge) | Δ |
|---|---|---|---|
| Sonnet 4.6 (vs golden) | 80% | **100%** | +20pp |
| GLM-5 | 40% | **60%** | +20pp |
| Kimi K2.5 | 60% | **20%** | -40pp |
| Qwen3 VL | 20% | 20% | 0 |
| DeepSeek V3.2 | 20% | 0% | -20pp |

### What the unbiased judge tells us

**The Sonnet self-judge was actually too lenient** on smaller models, not the opposite. When Opus 4.8 judges:

1. **Sonnet vs Sonnet (golden) is much closer to 100%** — the new candidate cards are essentially identical quality to the goldens, as expected when running the same model on the same papers.

2. **GLM-5 is the standout candidate** — Opus 4.8 rates it 4.90 average and 60% win rate. Almost matching Sonnet's quality. This is a meaningful upgrade in confidence vs the Sonnet-judged numbers.

3. **Kimi K2.5 looks worse under Opus 4.8** — drops from 60% win rate to 20%. The Sonnet-judge was over-rating Kimi's cards. Opus 4.8 sees them as clearly inferior to Sonnet's golden cards.

4. **Qwen3 VL and DeepSeek V3.2 stay weak** — both judges agree these are noticeably worse.

### Updated recommendation

**The new top candidate is GLM-5, not Kimi K2.5.**

| Model | Quality (Opus judge) | Win% (Opus judge) | $/paper | Recommendation |
|---|---|---|---|---|
| **GLM-5** | **4.90** | **60%** | $0.0246 | ⭐ Best balance: near-Sonnet quality at 4.2× cost reduction |
| Kimi K2.5 | 4.50 | 20% | $0.0166 | Cheaper but real quality regression — only worth it for cost-extreme tiers |
| Qwen3 VL | 4.35 | 20% | $0.0157 | Skip |
| DeepSeek V3.2 | 4.55 | 0% | $0.0150 | Skip — never wins head-to-head |

GLM-5 cost at 30 papers/day = ~$22/month per user. That's 75% reduction from Sonnet.

## Judge variance: 3-seed replication (Opus 4.8)

To check whether the rankings above are stable or noisy, we re-judged each candidate
3 times with different RNG seeds (controls A/B order randomization in the judge prompt).
Numbers below are mean ± standard deviation.

| Model | Relev (μ±σ) | Specif (μ±σ) | Calib (μ±σ) | Action (μ±σ) | Win% (μ±σ) |
|---|---|---|---|---|---|
| **Sonnet 4.6 (vs golden)** | **5.00±0.00** | **5.00±0.00** | **4.93±0.12** | **5.00±0.00** | **100.0±0.0** |
| GLM-5 | 5.00±0.00 | 5.00±0.00 | 4.60±0.20 | 4.73±0.12 | **53.33±11.55** |
| Kimi K2.5 | 4.60±0.00 | 4.87±0.12 | 4.20±0.00 | 4.40±0.20 | 20.00±0.00 |
| Qwen3 VL | 4.67±0.12 | 4.40±0.00 | 4.00±0.20 | 4.47±0.12 | 20.00±0.00 |
| DeepSeek V3.2 | 4.60±0.00 | 4.53±0.31 | 4.13±0.23 | 4.33±0.12 | 13.33±11.55 |

### What this tells us

**The rankings are robust to judge variance:**

1. **Dimensional scores are remarkably stable** — σ ≤ 0.3 on every dimension across all
   models. The judge consistently rates the same cards similarly across seeds.

2. **Win rates have meaningful but not damaging variance** — σ around 0-12pp.
   The bottom-tier models (Kimi/Qwen) are locked at 20%; GLM-5 swings 40-60%; Sonnet
   stays at 100%. The orderings never flip.

3. **The GLM-5 vs Kimi K2.5 gap is real, not noise.**
   GLM-5: 53% ± 12% win rate (range: 40-60%).
   Kimi K2.5: 20% ± 0% win rate (range: 20-20%).
   Even at GLM-5's worst seed (40%) it doubles Kimi's best seed (20%).

4. **Sonnet 4.6 vs golden is essentially deterministic** — 100% win rate every time.
   This makes sense: the candidate cards are very similar to the goldens (same model,
   same prompts, same papers).

### Conclusion

The single-run results were not noise. **GLM-5 is genuinely the strongest non-Sonnet
candidate** across multiple judge seeds. Migration recommendation stands.

## Option A: full replication (3 digest runs × 1 judge)

To control for **model variance** (not just judge variance — `temperature=0.7` on the
digest step means each run produces slightly different cards), we re-ran the full eval
3× per model. ~51 minutes total wall time, ~$8.50 in Bedrock costs.

### Results

| Model | Relev (μ±σ) | Specif (μ±σ) | Calib (μ±σ) | Action (μ±σ) | Win% (μ±σ) | $/paper | Latency |
|---|---|---|---|---|---|---|---|
| **Sonnet 4.6** | 5.00±0.00 | 5.00±0.00 | 4.80±0.00 | 5.00±0.00 | **86.67±11.55** | $0.1048 | 74s |
| GLM-5 | 5.00±0.00 | 4.87±0.12 | 4.63±0.15 | 4.72±0.10 | 56.67±20.82 | $0.0249 | 51s |
| **Kimi K2.5** | 4.80±0.00 | 4.93±0.12 | 4.73±0.12 | 4.73±0.12 | **60.00±0.00** | **$0.0166** | **30s** |
| Qwen3 VL | 4.67±0.12 | 4.47±0.12 | 4.07±0.23 | 4.47±0.12 | 26.67±11.55 | $0.0154 | 35s |
| DeepSeek V3.2 | 4.67±0.12 | 4.60±0.00 | 4.20±0.00 | 4.20±0.20 | 20.00±0.00 | $0.0150 | 35s |

### What flipped vs single-run results

**Kimi K2.5 came back as a serious contender.** Across 3 model runs, Kimi:
- Hit 60.00% win rate with **0% variance** — strikingly consistent
- Scored 4.93 specificity and 4.73 calibration — actually beat GLM-5 on these dimensions
- Sat at $0.0166/paper — 33% cheaper than GLM-5

GLM-5's win rate was **56.67% ± 20.82** — high variance. One run was 80%, another was 40%.
This means the original Sonnet-judge result that put GLM-5 ahead was likely **lucky** for
GLM-5 and **unlucky** for Kimi.

### Final ranking (with full variance accounted for)

| Rank | Model | Win% (3-run μ) | Quality avg | $/paper | Notes |
|---|---|---|---|---|---|
| 1 | **Sonnet 4.6** | 86.67% ± 11.55 | 4.95 | $0.1048 | Baseline, best quality |
| 2 | **Kimi K2.5** | **60.00% ± 0.00** | 4.80 | **$0.0166** | Most consistent candidate; 6.3× cheaper |
| 3 | GLM-5 | 56.67% ± 20.82 | 4.81 | $0.0249 | Quality on par with Kimi but cost is 50% higher and run-to-run quality less stable |
| 4 | Qwen3 VL | 26.67% ± 11.55 | 4.42 | $0.0154 | Below quality threshold |
| 5 | DeepSeek V3.2 | 20.00% ± 0.00 | 4.42 | $0.0150 | Consistently lowest |

### Key insights from Option A

1. **Kimi K2.5 is the most consistent model** — every dimension and win rate has either zero
   or low variance. You get the same quality every run.

2. **GLM-5 is a coin flip** — win rate ranged 40-80% across 3 runs. Calibration σ=0.15.
   Choosing GLM-5 means accepting more variance in card quality.

3. **Sonnet 4.6 isn't perfect either** — its self-vs-golden win rate was 86.67% ± 11.55, not
   the perfect 100% from single-run. Some natural variance from `temperature=0.7`.

4. **Cost ranking (μ):** Sonnet ($0.1048) → GLM-5 ($0.0249) → Kimi ($0.0166) → Qwen ($0.0154)
   → DeepSeek ($0.0150). The $0.001 differences at the bottom are noise.

5. **Calibration is the differentiator that Kimi nails** — Kimi's 4.73 calibration matches
   user level better than GLM-5's 4.63 across runs. Sonnet still leads at 4.80.

## Final recommendation (revised)

**Migrate digest to Kimi K2.5.**

Rationale (now backed by 3-run variance data):
- **Most consistent candidate** — 60% win rate with σ=0, vs GLM-5's σ=21
- **Cheapest viable option** — $0.0166/paper, 33% cheaper than GLM-5
- **Fastest** — 30s/paper, 2.5× faster than Sonnet
- **Calibration beats GLM-5** — 4.73 vs 4.63
- **Acceptable quality drop** — 4.80 avg vs Sonnet's 4.95 (3% gap)

Per-user cost projection:
- Sonnet 4.6 only: ~$94/month (~$3.13/day × 30 papers)
- **Kimi K2.5 digest + Sonnet chat: ~$20/month (~80% reduction)**

The hybrid keeps user-facing chat at Sonnet quality while moving the high-volume,
batch-oriented digest step to Kimi K2.5.

## Recommendation (revised after Opus 4.8 judge)

**Migrate digest to GLM-5. Keep chat on Sonnet 4.6.**

After cross-judging with Opus 4.8 (eliminating self-preference bias), GLM-5 emerged
as the strongest candidate:
- Quality: 4.90 avg (vs Sonnet's 5.00 — only 2% gap)
- Win rate: 60% — produces cards that Opus 4.8 considers competitive with Sonnet's
- Cost: $0.0246/paper — 4.2× cheaper than Sonnet
- Latency: 62s vs Sonnet's 70s

The Sonnet-judge had **over-rated Kimi K2.5** (gave it 60% win rate; Opus 4.8 says 20%).
Kimi is still a viable cheaper option but with a real quality drop.

This hybrid cuts monthly cost-per-user from ~$94 (all Sonnet) to ~$25 (GLM-5 digest +
Sonnet chat) — a **73% reduction** with minimal quality loss on digest.

Worth doing a 1-week canary: route 50% of digest runs to GLM-5, look at engagement
metrics + spot-check 5-10 cards for calibration drift, then commit.

## Run history

| Run | Model | Date | Run ID |
|---|---|---|---|
| Baseline | Sonnet 4.6 | 2026-06-26 | `2026-06-26T18:18:09.000Z` |
| Candidate | GLM-5 | 2026-06-26 | `2026-06-26T18:21:55.000Z` |
| Candidate | Kimi K2.5 | 2026-06-26 | `2026-06-26T18:31:02.000Z` |
| Candidate | Qwen3 VL 235B | 2026-06-26 | `2026-06-26T18:34:28.000Z` |
| Candidate | DeepSeek V3.2 | 2026-06-26 | `2026-06-26T18:39:42.000Z` |

Generated reports under `sarathi_eval_*.md` in repo root.

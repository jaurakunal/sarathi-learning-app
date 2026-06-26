# Sarathi Pipeline Steps Evaluation

_Generated: 2026-06-26 23:50 UTC_

_Baseline model: `us.anthropic.claude-sonnet-4-6`_

## Triage

Per-paper score (worth_my_hours bool + triage_score 0-1) compared to the live user's stored Sonnet outputs. MAE = mean absolute error on triage_score; Corr = Pearson correlation; Worth Acc = boolean accuracy.

| Model | Papers | Score MAE | Score Corr | Worth Acc | Level Acc | $/paper | Latency (ms) |
|---|---|---|---|---|---|---|---|
| `us.anthropic.claude-sonnet-4-6` | 18.0/18.0 | 0.100 | 0.558 | 0.556 | 0.944 | $0.0066 | 4198.0 |
| `moonshotai.kimi-k2.5` | 18.0/18.0 | 0.096 | 0.264 | 0.944 | 0.944 | $0.0011 | 20547.0 |
| `zai.glm-5` | 18.0/18.0 | 0.111 | 0.590 | 0.944 | 0.944 | $0.0016 | 4475.0 |
| `us.anthropic.claude-sonnet-4-6` | 68.0/68.0 | 0.043 | 0.983 | 0.897 | 0.943 | $0.0055 | 3145.0 |
| `moonshotai.kimi-k2.5` | 68.0/68.0 | 0.108 | 0.969 | 1.000 | 0.679 | $0.0010 | 1993.0 |
| `zai.glm-5` | 68.0/68.0 | 0.093 | 0.922 | 0.971 | 0.547 | $0.0014 | 4480.0 |

**Recommendation:** `moonshotai.kimi-k2.5` — best balance of accuracy (worth_acc=1.000, score_mae=0.108) and cost ($0.0010/paper).

## Lens

Hypothesis-relevance annotation. Verdict match = fraction where the candidate reaches the same supports/refutes/refines verdict as Sonnet. Coherent = LLM-as-judge says reasoning is well-grounded. Lens align = both verdict matches AND reasoning coherent.

| Model | Papers | Verdict Match % | Coherent % | Lens Align % | $/paper | Latency (ms) |
|---|---|---|---|---|---|---|
| `us.anthropic.claude-sonnet-4-6` | 5.0/18.0 | 40.0 | 60.0 | 20.0 | $0.0035 | 4030.0 |
| `moonshotai.kimi-k2.5` | 5.0/18.0 | 40.0 | 80.0 | 40.0 | $0.0006 | 31370.0 |
| `zai.glm-5` | 5.0/18.0 | 40.0 | 80.0 | 40.0 | $0.0008 | 4149.0 |
| `us.anthropic.claude-sonnet-4-6` | 55.0/68.0 | 56.4 | 89.1 | 52.7 | $0.0016 | 2602.0 |
| `moonshotai.kimi-k2.5` | 55.0/68.0 | 63.6 | 89.1 | 58.2 | $0.0003 | 1720.0 |
| `zai.glm-5` | 55.0/68.0 | 50.9 | 85.5 | 49.1 | $0.0003 | 2609.0 |

**Recommendation:** `moonshotai.kimi-k2.5` — top lens_alignment (58.2%) at $0.0003/paper.

## Relevance Filter

Coarse pre-triage filter. Positives = the 18 dataset papers (which passed in production). Negatives = synthetic off-topic papers shipped with the eval. Precision = of papers kept, fraction that should be kept; Recall = of papers that should be kept, fraction actually kept.

| Model | Papers | Accuracy | Precision | Recall | F1 | $/paper | Avg Latency (ms) |
|---|---|---|---|---|---|---|---|
| `us.anthropic.claude-sonnet-4-6` | 30.0/30.0 | 1.000 | 1.000 | 1.000 | 1.000 | $0.00029 | 1910.0 |
| `moonshotai.kimi-k2.5` | 30.0/30.0 | 1.000 | 1.000 | 1.000 | 1.000 | $0.00005 | 12171.0 |
| `zai.glm-5` | 30.0/30.0 | 1.000 | 1.000 | 1.000 | 1.000 | $0.00008 | 3219.0 |
| `us.anthropic.claude-sonnet-4-6` | 25.0/43.0 | 0.960 | 0.947 | 1.000 | 0.973 | $0.00024 | 724.0 |
| `moonshotai.kimi-k2.5` | 25.0/43.0 | 0.920 | 0.900 | 1.000 | 0.947 | $0.00004 | 597.0 |
| `zai.glm-5` | 43.0/43.0 | 0.698 | 0.581 | 1.000 | 0.735 | $0.00006 | 12034.0 |

**Recommendation:** `us.anthropic.claude-sonnet-4-6` — best F1 (1.000) at $0.00029/paper.

## Learn

Profile-update suggestions. Alignment = LLM-as-judge score (1-5) for similarity vs Sonnet baseline output on the same input.

| Model | Areas | Hypothesis | Summaries | Style | Overall | Cost | Latency (ms) |
|---|---|---|---|---|---|---|---|
| `us.anthropic.claude-sonnet-4-6` | 5.000 | 5.000 | 5.000 | 5.000 | **5.000** | $0.0208 | 19683.0 |
| `moonshotai.kimi-k2.5` | 4.000 | 4.000 | 4.000 | 5.000 | **4.000** | $0.0256 | 16100.0 |
| `zai.glm-5` | 5.000 | 5.000 | 4.000 | 5.000 | **5.000** | $0.0233 | 24099.0 |
| `us.anthropic.claude-sonnet-4-6` | 5.000 | 5.000 | 5.000 | 5.000 | **5.000** | $0.0197 | 18623.0 |
| `moonshotai.kimi-k2.5` | 5.000 | 5.000 | 4.000 | 5.000 | **5.000** | $0.0254 | 9193.0 |
| `zai.glm-5` | 5.000 | 4.000 | 4.000 | 5.000 | **5.000** | $0.0245 | 5904.0 |

**Recommendation:** `us.anthropic.claude-sonnet-4-6` — top overall_alignment (5.000/5).

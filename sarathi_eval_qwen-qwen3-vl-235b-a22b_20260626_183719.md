# Sārathi LLM Evaluation Report

_Generated: 2026-06-26 18:37 UTC_

_Baseline model: `us.anthropic.claude-sonnet-4-6`_

## Comparison Table

| Model | Papers | Relev. | Specif. | Calib. | Action. | Align% | Win% | $/paper | Latency (ms) |
|---|---|---|---|---|---|---|---|---|---|
| `us.anthropic.claude-sonnet-4-6` | 0/18 | — | — | — | — | — | — | — | 0 |
| `us.anthropic.claude-sonnet-4-6` | 5/18 | — | — | — | — | — | — | $0.0963 | 70121 |
| `us.anthropic.claude-sonnet-4-6` | 16/18 | 4.60 | 4.60 | 4.60 | 4.60 | 0.0 | 80.0 | $0.0996 | 80051 |
| `us.zai.glm-5` | 0/18 | 0.00 | 0.00 | 0.00 | 0.00 | 0.0 | 0.0 | — | 10359 |
| `zai.glm-5` | 17/18 | 4.60 | 4.40 | 4.20 | 4.40 | 0.0 | 20.0 | $0.0850 | 45478 |
| `us.anthropic.claude-sonnet-4-6` | 18/18 | 4.80 | 4.80 | 4.80 | 4.80 | 0.0 | 80.0 | $0.1045 | 69524 |
| `zai.glm-5` | 15/18 | 4.80 | 4.60 | 4.40 | 4.60 | 0.0 | 40.0 | $0.0246 | 62221 |
| `moonshotai.kimi-k2.5` | 17/18 | 4.60 | 4.60 | 4.20 | 4.60 | 0.0 | 60.0 | $0.0166 | 20291 |
| `qwen.qwen3-vl-235b-a22b` | 18/18 | 4.40 | 4.40 | 4.00 | 4.60 | 0.0 | 20.0 | $0.0157 | 36634 |

## Score Definitions

- **Relev.** — Does the hook connect to the user's research interests? (1-5)
- **Specif.** — Is the hook about THIS paper's contribution, or generic? (1-5)
- **Calib.** — Does the explanation match user's level (math comfort, depth)? (1-5)
- **Action.** — Does it surface 'why now' / what to do with this? (1-5)
- **Align%** — Judge's engagement prediction vs user's actual engagement
- **Win%** — Win rate vs baseline (Sonnet 4.6) on per-paper head-to-head
- **$/paper** — Approximate Bedrock cost per paper digested

## Run Details

### `us.anthropic.claude-sonnet-4-6`

- **Run ID:** `2026-06-25T22:37:27.191Z_018fee38`
- **Papers:** 0/18 succeeded
- **Cost per paper:** N/A
- **Avg latency:** 0 ms

### `us.anthropic.claude-sonnet-4-6`

- **Run ID:** `2026-06-25T22:40:11.589Z_9eaee96d`
- **Papers:** 5/18 succeeded
- **Cost per paper:** $0.0963
- **Avg latency:** 70121 ms

### `us.anthropic.claude-sonnet-4-6`

- **Run ID:** `2026-06-25T22:47:11.492Z_00ac1b49`
- **Judge model:** `us.anthropic.claude-sonnet-4-6`
- **Papers:** 16/18 succeeded
- **Cost per paper:** $0.0996
- **Avg latency:** 80051 ms

### `us.zai.glm-5`

- **Run ID:** `2026-06-26T17:48:11.791Z_d0658cba`
- **Judge model:** `us.anthropic.claude-sonnet-4-6`
- **Papers:** 0/18 succeeded
- **Cost per paper:** N/A
- **Avg latency:** 10359 ms

### `zai.glm-5`

- **Run ID:** `2026-06-26T17:56:31.976Z_32c42f51`
- **Judge model:** `us.anthropic.claude-sonnet-4-6`
- **Papers:** 17/18 succeeded
- **Cost per paper:** $0.0850
- **Avg latency:** 45478 ms

### `us.anthropic.claude-sonnet-4-6`

- **Run ID:** `2026-06-26T18:15:14.286Z_14f0a7e5`
- **Judge model:** `us.anthropic.claude-sonnet-4-6`
- **Papers:** 18/18 succeeded
- **Cost per paper:** $0.1045
- **Avg latency:** 69524 ms

### `zai.glm-5`

- **Run ID:** `2026-06-26T18:20:43.987Z_cc68151d`
- **Judge model:** `us.anthropic.claude-sonnet-4-6`
- **Papers:** 15/18 succeeded
- **Cost per paper:** $0.0246
- **Avg latency:** 62221 ms

### `moonshotai.kimi-k2.5`

- **Run ID:** `2026-06-26T18:31:08.169Z_e1ac70fb`
- **Judge model:** `us.anthropic.claude-sonnet-4-6`
- **Papers:** 17/18 succeeded
- **Cost per paper:** $0.0166
- **Avg latency:** 20291 ms

### `qwen.qwen3-vl-235b-a22b`

- **Run ID:** `2026-06-26T18:34:16.660Z_9fa56393`
- **Judge model:** `us.anthropic.claude-sonnet-4-6`
- **Papers:** 18/18 succeeded
- **Cost per paper:** $0.0157
- **Avg latency:** 36634 ms

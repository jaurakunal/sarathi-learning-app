# 07 — M0 Build Plan

**M0 answers one question: "Do the hooks make me want to read?"**

Done = you're scrolling real feed cards on your phone, generated from real papers, personalized to your profile. If the hooks pull you in, M0 succeeded. If not, we fix the hooks before building anything else.

---

## Dependencies (what blocks what)

```
[1] Seed profile ─────────────────────────────────────┐
                                                       ▼
[2] CDK: DDB table + S3 bucket ──────────────────► [5] Pipeline: Discover
                                                       │
[3] CDK: Cognito ─────────────────────────────────┐    ▼
                                                   │ [6] Pipeline: Triage
[4] LLM bake-off (can run locally, no infra) ─────┤    │
                                                   │    ▼
                                                   │ [7] Pipeline: Select
                                                   │    │
                                                   │    ▼
                                                   │ [8] Pipeline: Digest (Fargate)
                                                   │    │
                                                   │    ▼
                                                   │ [9] Pipeline: Lens + Publish
                                                   │    │
                                                   │    ▼
[10] CDK: Step Functions (orchestrate 5-9) ◄───────┤ [11] CDK: EventBridge (nightly trigger)
                                                   │
[12] CDK: API Gateway + Feed Lambda ◄─────────────┤
                                                   │
[13] CDK: CloudFront (static SPA) ◄───────────────┘
                                                   
[14] Frontend: minimal scrollable feed ────────────► [15] Deploy + test on phone
```

---

## Steps (ordered for execution)

### Phase A: Foundation (no AWS deploy yet — local + design)

| # | Step | What to do | Done when | Depends on |
|---|---|---|---|---|
| A1 | Seed profile into code | Convert the onboarding interview (docs/04, docs/05) into a concrete `seed_profile.py` that writes all PROFILE items to DDB (META, AREAs, HYPOTHESIS, SUMMARYs). Hard-code the Kunal profile from the interview. | Profile items can be written to DDB with one script call | — |
| A2 | LLM bake-off | Pick ~5 real papers (including Generative Agents). Run triage + hook + digest on each with 2-3 models (Opus, Sonnet, one open-source). Blind-rank outputs. Decide model-per-task. Log results to `experiments/`. | Model choice locked per task, with data to back it | — |
| A3 | Implement arXiv source | Fill `backend/sources/arxiv.py`: query arXiv API by category/keywords derived from areas, normalize results to `Paper` model, fetch full text (PDF→text). | Can run `ArxivSource().discover(areas, since)` locally and get real papers back | — |
| A4 | Implement Semantic Scholar source | Fill `backend/sources/semantic_scholar.py`: query S2 API, normalize to `Paper`, fetch full text via S2's open access links. | Same as A3 for S2 | — |
| A5 | Implement HF Daily Papers source | Fill `backend/sources/hf_daily_papers.py`: scrape/API the HF daily papers page, normalize. | Same as A3 for HF | — |
| A6 | Implement OpenReview source | Fill `backend/sources/openreview.py`: query OpenReview API, normalize, capture reviewer scores. | Same as A3 for OpenReview | — |

**A1 and A2 can happen in parallel. A3-A6 can all happen in parallel with each other (and with A2).**

### Phase B: Pipeline logic (runs locally against real data, no AWS yet)

| # | Step | What to do | Done when | Depends on |
|---|---|---|---|---|
| B1 | Implement DDB access layer | `backend/shared/db.py` — functions for all access patterns (get_profile, put_paper, query_feed, put_feed_card, etc.). Uses boto3. Testable against DDB Local or real table. | All access patterns from docs/06 have working functions | A1 |
| B2 | Implement Discover step | Fill `backend/pipeline/discover.py`: read profile areas from DDB, call all sources, dedup against existing papers, write new candidates to DDB. | Can run locally → papers appear in DDB | A3-A6, B1 |
| B3 | Implement Triage step | Fill `backend/pipeline/triage.py`: read candidates + profile from DDB, call LLM to score each (using model from A2), update triage_score/reasoning on each paper. | Can run locally → papers have scores | A2, B1, B2 |
| B4 | Implement Select step | Fill `backend/pipeline/select.py`: rank triaged papers, apply budget cap + quality floor, mark top ones as 'surfaced'. | Can run locally → ~3-5 papers marked surfaced | B3 |
| B5 | Implement Digest step | Fill `backend/pipeline/digest.py`: for surfaced papers, fetch full text, store in S3, call LLM to generate hook + digest + glossary + math_notes + hypothesis_relevance + honesty_note + suggested_questions. Write feed_card to DDB. | Can run locally → feed_cards in DDB with real hooks/digests | A2, B4 |
| B6 | Implement Lens step | Fill `backend/pipeline/lens.py`: read feed_cards, evaluate against hypothesis, update hypothesis_relevance. (May merge into B5 if trivial.) | feed_cards have hypothesis_relevance populated | B5 |
| B7 | End-to-end local pipeline test | Run discover → triage → select → digest → lens locally (manually calling each in sequence). Verify ~5 real feed_cards in DDB. **Read the hooks yourself — do they pull you?** | You've scrolled the raw JSON output and felt something | B2-B6 |

**B2-B6 are sequential (each feeds the next). B1 can start as soon as A1 is done.**

### Phase C: Infrastructure (CDK deploy)

| # | Step | What to do | Done when | Depends on |
|---|---|---|---|---|
| C1 | CDK: DDB table | Single table, on-demand billing, all GSIs (1-4). | `cdk deploy` creates the table | — |
| C2 | CDK: S3 bucket | Paper texts + static assets. User-scoped key structure. | Bucket exists | — |
| C3 | CDK: Cognito | User pool + app client + hosted UI. Create your one user. | Can log in via hosted UI and get a JWT | — |
| C4 | CDK: Lambda functions | Package discover, triage, select, lens as Lambda functions. IAM roles with DDB/S3/Secrets access. | Lambdas deployed and invocable | C1, C2, B2-B4, B6 |
| C5 | CDK: Fargate task def | Digest step as a Fargate task. VPC with public subnet, no NAT. ECR image. | Task definition registered, image pushed | C1, C2, B5 |
| C6 | CDK: Step Functions | State machine wiring: Discover → Triage → Select → Digest → Lens+Publish. Error handling + retries. | State machine exists and can be started manually | C4, C5 |
| C7 | CDK: EventBridge | Nightly cron trigger for the state machine. | Pipeline runs automatically at scheduled time | C6 |
| C8 | CDK: API Gateway | Routes: GET /feed (paginated), GET /feed/{card_id}. Cognito JWT authorizer. | Can curl the feed API with a valid JWT and get cards | C3, C4 |
| C9 | CDK: CloudFront | Distribution pointing to S3 (static SPA assets). | HTTPS URL serves the SPA | C2 |
| C10 | Seed profile to DDB | Run the seed script (A1) against the real deployed table. | Profile items exist in prod DDB | A1, C1 |
| C11 | Run pipeline once manually | Start the Step Functions execution. Verify feed_cards land in DDB. | Real cards queryable via feed API | C6, C10 |

**C1-C3 can deploy in parallel (no deps between them). C4-C5 need the table + bucket + pipeline code. C6 needs C4+C5. C8 needs C3+C4.**

### Phase D: Frontend (minimal — prove the scroll)

| # | Step | What to do | Done when | Depends on |
|---|---|---|---|---|
| D1 | Choose framework | Pick a lightweight SPA framework. Rec: React (you know JS) or even plain HTML+JS for v0 speed. | Decision made | — |
| D2 | Build scrollable feed | A single page: fetches GET /feed, renders cards with progressive disclosure (hook visible, tap to expand gist → key_ideas → deep). Glossary inline. | Page renders real cards in a browser | C8 |
| D3 | Build auth flow | Cognito hosted UI redirect → get JWT → attach to API calls. | Can log in on the phone and see your feed | C3, D2 |
| D4 | Deploy to S3 + CloudFront | Build frontend, upload to S3, invalidate CloudFront. | Live URL accessible from phone | C9, D3 |
| D5 | Scroll on phone | Open the URL on your phone. Scroll. **Does this beat Twitter?** | You answer yes/no honestly | D4 |

---

## The real test (D5)

D5 is the only step that matters. Everything before it exists to get you there. If D5 = "no, these hooks are boring" → go back to A2/B5 and iterate on the prompts. If D5 = "yes, I want to read these" → M0 is done, move to M1.

---

## What's explicitly NOT in M0

- Engagement logging (M1)
- Profile learning loop (M1)
- Streaming chat / Q&A (M1)
- Library graduation + rewrites (M1)
- Conversation history (M1)
- Tiered summary regeneration (M1 — summaries are seeded, not learned)
- Weekly deep brief (M2)
- Hypothesis tracking UI (M2)
- Vector embeddings / RAG (M2)

---

## Estimated effort (rough)

| Phase | Effort | Parallelizable |
|---|---|---|
| A (foundation) | 2-3 days | A1-A6 mostly parallel |
| B (pipeline logic) | 3-5 days | Sequential (each step feeds next) |
| C (CDK deploy) | 2-3 days | C1-C3 parallel, then C4-C9 mostly parallel |
| D (frontend) | 1-2 days | Sequential |
| **Total** | **~8-13 days** | With focused effort |

This assumes evenings/weekends since you have a day job. Adjust to reality.

---

## Order of attack (my recommendation)

1. **A1 + A2 + A3 first** (profile seed + bake-off + arXiv source) — these unblock everything and give you real data to test with immediately.
2. **B1-B7** in sequence — prove the pipeline works locally before touching AWS.
3. **C1-C11** — deploy infra, run for real.
4. **D1-D5** — frontend last (it's the smallest piece and depends on everything else).

The bake-off (A2) is the most important single step — it decides whether the hooks are good enough to beat Twitter, which is the whole point. Don't skip it even if you're eager to deploy.

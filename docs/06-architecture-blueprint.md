# 06 — Architecture Blueprint (v0)

The concrete technical architecture for Sārathi v0. Everything here was decided through discussion — reasons are documented alongside decisions.

---

## AWS Shape

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PIPELINE (nightly, Step Functions orchestration)                         │
│                                                                          │
│  EventBridge ──► Step Functions                                          │
│                    ├─ Discover      → Lambda                             │
│                    ├─ Triage        → Lambda                             │
│                    ├─ Select        → Lambda                             │
│                    ├─ Digest        → Fargate (ECS RunTask)              │
│                    ├─ Lens+Publish  → Lambda                             │
│                    └─ Learn         → Lambda                             │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  SERVING (always available)                                              │
│                                                                          │
│  CloudFront ──► S3 (static SPA + feed.json + digests + paper texts)      │
│       │                                                                  │
│       └──► API Gateway ──► Lambda (engagement logging)                   │
│                                                                          │
│  Lambda Function URL (SSE streaming) ──► DynamoDB (conversations)        │
│                                                                          │
│  Cognito (auth — one user pool, Hosted UI, JWT authorizer)               │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  STORAGE                                                                 │
│                                                                          │
│  S3:  static site / feed.json / paper full texts / profile.json          │
│  DDB: engagement events / conversations (single-table)                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key decisions & reasoning

| Decision | Choice | Why |
|---|---|---|
| Pipeline compute | Step Functions → Lambda (short) + Fargate (digest) | Right tool per step. Lambdas for <15 min work; Fargate for the long LLM-heavy digest step. |
| NO NAT Gateway | Public subnet + `assignPublicIp: ENABLED` | NAT = ~$33/mo fixed (10-30× all other infra). Fargate in public subnet + security groups blocking inbound = safe for a batch job. VPC Gateway Endpoints for S3/DDB (free). |
| NO AWS Batch (v0) | ECS RunTask directly from Step Functions | Batch earns its keep for fan-out/Spot; v0 digests a handful of papers. |
| NO Spot (v0) | On-demand Fargate | Compute is cents/month; LLM API calls are ~95% of the bill. Optimizing compute = optimizing the cheap part. |
| Spot readiness | Digest step isolated in its own task | Flipping to Spot later = config change on one step, not a redesign. |
| Idempotent steps | All steps are idempotent by design | Step Functions gives retries + state for free. Correct regardless of Spot. |
| Streaming chat | Lambda Function URL + SSE | Serverless, Python, full control over prompts/grounding. No always-on cost. |
| Auth | Cognito | One user, but data is psych profile + reading habits + unpublished thesis = worth real auth. Cognito does site + API with one mechanism. |
| NO AgentCore (v0) | Own the session management | Cheaper long-term, full control over conversation state in DDB. |

### No-op stubs (shipped in v0 code, not implemented)

```python
class InterruptionHandler(Protocol):
    """Seam for Spot instance interruption handling."""
    def checkpoint(self, state: PipelineState) -> None: ...
    def resume(self) -> PipelineState | None: ...

class NoOpInterruptionHandler:
    """v0: on-demand, no interruptions. Fill when Spot is added."""
    def checkpoint(self, state): pass
    def resume(self): return None

class InternalSource(PaperSource):
    """v0: external-only. Needs SSO auth to implement."""
    name = "internal"
    def discover(self, areas, since):
        raise NotImplementedError("v0 is external-only")
    def fetch_full_text(self, paper_id):
        raise NotImplementedError
```

### Cost estimate (v0, monthly, 1 user)

| Component | Cost | Notes |
|---|---|---|
| Fargate (nightly, ~30 min, 1 vCPU/2GB) | ~$1-3 | On-demand |
| S3 | cents | feed + papers + site |
| DynamoDB (on-demand) | cents | tiny event volume |
| Lambda | pennies | within/near free tier |
| CloudFront | $0 | 1TB/mo free tier |
| Cognito | $0 | free up to 10K MAU |
| API Gateway | pennies | one user |
| NAT Gateway | **$0** | avoided by design |
| **AWS infra total** | **~$2-5/mo** | |
| **LLM API calls** | **~$5-50/mo** | **The real cost** |

---

## Pipeline Steps (nightly)

```
1. DISCOVER    Read profile areas → query sources → candidate papers
2. TRIAGE      LLM reads each abstract + profile → rank by relevance/level/hypothesis fit
3. SELECT      Budget-cap (best N for ~2-4 hrs) + quality floor
4. DIGEST      Fetch full text → store in S3 → generate hook + multi-level digest + glossary
5. LENS        Tag hypothesis relevance (supports/refutes/refines)
6. PUBLISH     Write feed.json + per-paper digests to S3
7. LEARN       Read engagement events → update profile.json → regenerate ALL summaries
```

### Pipeline details

**Discover:** queries all sources via `PaperSource` interface. Each source normalizes to the same `paper` record shape. v0 ships 4 sources (arXiv, Semantic Scholar, OpenReview, HF Daily Papers).

**Triage is a RANK, not a fixed threshold.** Logic:
1. Score all candidates (relevance + right-level + hypothesis-fit).
2. Budget-cap: select only as many as fit the time estimate (~3 deep, or ~5 micro-digests).
3. Quality floor: "is the best one better than re-reading from Library?" If no → dry-week mode.

**Dry-week mode (bot never goes silent):**

| Card type | What it does |
|---|---|
| `resurface` | Re-surfaces a library paper with a new angle you missed |
| `connect` | "Paper A + Paper B = a connection you haven't made" |
| `brainstorm` | "Here's a question at the intersection — want to think through it?" |
| `revisit_hypothesis` | "3 papers touch the hypothesis — here's the scorecard" |
| `challenge` | "Strongest counterargument to your thesis from what you've read" |

The bot is transparent: "Dry week. Nothing new worth your time. Let's go deeper on something you've read."

**Digest (the expensive step):** full paper text fetched and stored in S3 at this stage — always, regardless of later engagement. Cost: ~$0.01/mo for a year of papers. Already paying LLM inference; storing text = free resilience + enables Q&A grounding without re-fetching from arXiv.

**Learn (nightly):** reads engagement events → LLM updates profile.json. Regenerates ALL tiered summaries (yesterday/3d/7d/month/quarter) if there was activity. Cost: fractions of a cent.

---

## Source Interface

```python
class PaperSource(Protocol):
    name: str
    def discover(self, areas: list[Area], since: datetime) -> list[RawPaper]: ...
    def fetch_full_text(self, paper_id: str) -> str | None: ...
```

Each source normalizes to the same `paper` record. Source-specific value captured as optional fields (e.g., OpenReview → `peer_review_signal`; Semantic Scholar → citation graph).

**v0 sources:**

| Source | Value add |
|---|---|
| arXiv | Broad CS/physics/math papers, API available |
| Semantic Scholar | Citation graph, "papers that cite the one you liked," influence metrics |
| OpenReview | Peer-reviewed ML/AI + reviewer scores (feeds `honesty_note`) |
| HF Daily Papers | Curated, trending, social signal — best fit for "scroll instead of Twitter" |
| *(stub)* Internal | Needs SSO auth; `NotImplementedError` for v0 |

Adding a source = one new class implementing `PaperSource`, zero pipeline changes.

---

## Data Models

Six data objects + one journal. A paper progresses through them as it earns its way deeper in.

### The lifecycle (one paper's journey through the system)

```
profile.json ──reads──► [200 papers] ──triage──► paper records (machine, abstract)
     ▲                                                │ top ~5 survive
     │                                                ▼
     │                                        feed_card (hook + glossary + digest)
     │                                                │ you tap "read"
     │                                                ▼
     │                                        library_entry (full text rewrite at your level)
     │                                                │ you ask questions
     │                                                ▼
     │                                        conversation (scoped, cited, persistent)
     │                                                │ every action
     │                                                ▼
     └──────nightly learning loop◄──────── engagement_event (taps, questions, scroll)
                                                      │
                                            profile_history (the journey log)
```

### 1. `profile.json` — the brain (current state)

The standing instructions the pipeline reads every night. The only object that isn't about a paper.

```jsonc
{
  "areas": [
    {
      "id": "person-clone-personality",
      "label": "Person-cloning / mental models",
      "status": "active",           // active | dormant | archived
      "role": "spine",              // spine | secondary | seam
      "links": ["agent-memory", "contemplative-memory"],
      "frontier": "Built a cloning prototype cold; hasn't read Generative Agents;
                   doesn't know 'reflection' formally.",
      "too_basic": ["intro to RAG", "what are agents"],
      "just_right": ["memory architectures", "agent personas"],
      "added_at": "2026-06-10"
    }
    // Adding 'physics' or 'learn-rust' = just another record, zero code change.
  ],
  "hypothesis": {
    "statement": "Brain-structure + agentic harness >> the LLM.",
    "status": "untested",
    "supporting": [], "refuting": [], "refining": []
  },
  "learning_style": {
    "math": "route-around; tap-to-reveal only; never gate",
    "lead_with": "applied / can-I-use-this",
    "tone": "sharp mirror, no flattery, credit at exact scope"
  },
  "reading_speed": {
    "initial_idle_threshold_s": 60,
    "current_idle_threshold_s": 60,
    "avg_active_ms_per_card": null,
    "confidence": "low",
    "last_calibrated": null
  },
  "summaries": {
    "yesterday": "...",
    "3_day": "...",
    "7_day": "...",
    "month": "...",
    "quarter": "..."
  },
  "paper_goal": "Accumulate citations/claims/gaps toward my own paper.",
  "last_updated": "..."
}
```

**Tiered summaries:** ALL regenerated nightly if there was any activity that day. The agent reads these for context — NOT the raw history. These are the agent's working memory: pre-digested, bounded. Each tier compresses raw events into what matters for the profile.

### 2. `profile_history` — append-only journal

```jsonc
[
  { "ts": "2026-06-10", "type": "area_added",
    "area_id": "person-clone-personality",
    "reason": "Seeded from onboarding interview" },
  { "ts": "2026-08-15", "type": "frontier_moved",
    "area_id": "person-clone-personality",
    "old_frontier": "Hasn't read Generative Agents",
    "new_frontier": "Read GenAgents + MemGPT; exploring reflection architectures",
    "evidence": "Asked 4 questions about memory consolidation this week" },
  { "ts": "2027-01-10", "type": "area_deprioritized",
    "area_id": "adversarial-security",
    "reason": "No engagement in 6 weeks; moved to dormant" }
]
```

Raw source of truth. Never deleted. Powers the "intellectual journey" narrative for the future paper. Summaries compress it; the nightly pipeline reads summaries, not this.

### 3. `paper` — triage record (machine-facing; never shown to user)

```jsonc
{
  "id": "2304.03442",
  "source": "arxiv",
  "title": "Generative Agents: Interactive Simulacra of Human Behavior",
  "authors": ["Park et al."],
  "abstract": "<the authors' own dense abstract>",
  "url": "https://arxiv.org/abs/2304.03442",
  "published": "2023-04-07",
  "areas_matched": ["person-clone-personality", "agent-memory"],
  "triage_score": 0.94,
  "triage_reasoning": "Directly hits spine; he built this cold and hasn't read it.
                       Sweet-spot level. Hypothesis-relevant (memory architecture).",
  "worth_my_hours": true,
  "status": "candidate"    // candidate | surfaced | skipped | graduated
}
```

### 4. `feed_card` — the product (what you scroll)

```jsonc
{
  "paper_id": "2304.03442",
  "source_url": "https://arxiv.org/abs/2304.03442",
  "full_text_s3_key": "papers/2304.03442/full_text.txt",
  "card_type": "new_paper",    // new_paper | resurface | connect | brainstorm | revisit_hypothesis | challenge
  "hook": "You built this cold two years ago. Stanford published it first — and
           they added the one piece you were missing: reflection.",
  "why_you_now": "This is the formal version of your cloning prototype. Read it to
                  steal 'reflection' for your memory-connections product.",
  "time_estimate": "18 min",
  "digest": {
    "gist": "...",
    "key_ideas": ["..."],
    "deep": "..."
  },
  "glossary": [
    { "term": "reflection",
      "plain": "When an agent pauses, looks back over raw memories, and synthesizes
               higher-level conclusions. Those conclusions become new, reusable memories." },
    { "term": "memory stream",
      "plain": "The raw log of everything the agent observed or did — unprocessed,
               chronological, like a diary with no editing." }
  ],
  "math_notes": [
    { "plain": "They weight memories by recency, importance, and relevance — a simple score.",
      "equation_optional": "score = α·recency + β·importance + γ·relevance" }
  ],
  "hypothesis_relevance": "Supports the bet — the architecture (memory stream + reflection)
                           drives behavior, not raw model size.",
  "honesty_note": "Landmark paper, genuinely worth the full read — not hype.",
  "suggested_questions": ["What exactly is reflection?", "Could I add this to my product?"]
}
```

**Generated in two passes:**
1. Hook + why_you_now from abstract + profile (cheap, Lambda).
2. Digest + glossary + math_notes from full text (expensive, Fargate).

**Glossary:** plain-language definitions at *your current level* for terms in *this specific card*. Makes cards self-contained.

### 5. `library_entry` — graduated (earned by engagement)

```jsonc
{
  "paper_id": "2304.03442",
  "source_url": "https://arxiv.org/abs/2304.03442",
  "full_text_s3_key": "papers/2304.03442/full_text.txt",
  "rewrite": "<the full paper, re-explained at your altitude, with your product
              and hypothesis woven in as anchors throughout>",
  "read_at": "2026-06-20",
  "my_reactions": ["The reflection trees are basically what I wanted to build"],
  "extracted_claims": ["Reflection = periodic synthesis of observations into higher-level memories"],
  "potential_citation": "Park et al. 2023 — foundational for personality-clone related work",
  "divergence_notes": "They use an LLM for reflection; my thesis says the structure matters more"
}
```

**`rewrite` vs. `feed_card.digest`:** the digest *teases* (short, to provoke engagement). The rewrite *teaches* (long, full paper at your altitude with your product/hypothesis woven in). Most expensive single generation — triggered only by your explicit engagement.

### 6. `engagement_event` — behavioral signal (DynamoDB)

```jsonc
{
  "ts": "2026-06-20T10:30:00Z",
  "paper_id": "2304.03442",
  "action": "read",        // view | expand | read | rate | ask | dismiss | bookmark
  "active_ms": 210000,     // tab-visible + interactions (NOT raw dwell)
  "scroll_depth_pct": 85,
  "interactions": 7
}
```

**Signal hierarchy (cleanest → noisiest):**
1. Asked a question (strongest — typed intent)
2. Expanded a section (deliberate tap)
3. Dismissed / bookmarked (strong, including negative)
4. Scrolled through (medium — could be skimming)
5. Dwelled (weakest — supporting only)

**Adaptive idle threshold:**
- **Bootstrap (first 2 weeks):** P50 average reading speed (~250 wpm for technical content).
- **Calibrate:** after ~20 engagement events, calculate *your* actual reading pace from `active_ms` + `scroll_depth_pct`.
- **Update:** drift with you as you speed up in an area. Stored in `profile.json → reading_speed`.

**Noise filtering:**
- Tab visibility API: stop counting when browser backgrounded / phone locked.
- Scroll depth: if content scrolled during dwell = reading. If 0% = away.
- Interaction heartbeat: taps/scrolls within window = "still here." Threshold adapts per above.

### 7. `conversation` — Q&A (DynamoDB single-table)

**Three scopes:**

| Scope | Context strategy | v0 status |
|---|---|---|
| Single paper | Full text as LLM context (~30-50K tokens, fits in 200K window) | **Shipped** |
| Single area | Summaries + RAG for specific passages | Stubbed |
| Full library | RAG — vector search over corpus, retrieve relevant chunks | Stubbed |

v0 = single-paper Q&A only. No vector store needed. Area/library scopes added when library has ~10+ papers.

---

## DynamoDB Design (Single-Table, Paired Turns)

Conversations use **paired request+response turns** — a response without its request is meaningless; they're a unit.

### Schema

All PKs are prefixed with `USER#<cognitoSub>` for tenant isolation from day one. Cost: zero (sub is already in the JWT). Cost of adding later: full table migration to rewrite every PK. This is "engineer the internals clean," not multi-tenancy — no user management UI, no stranger onboarding, no multi-tenant features. Just means the data *could* be isolated later without a migration.

```
PK                                          SK              Attributes
─────────────────────────────────────────── ─────────────── ──────────────────────────────────
USER#<sub>#CONV#conv_abc123                 META            scope, paper_id, created_at,
                                                            last_active, full_text_s3_key

USER#<sub>#CONV#conv_abc123                 TURN#00001      request, request_ts, response,
                                                            response_ts, citations[],
                                                            tokens_in, tokens_out

USER#<sub>#CONV#conv_abc123                 TURN#00002      (same shape)
...
USER#<sub>#CONV#conv_abc123                 TURN#00015      type: "summary", content,
                                                            batch_id: "batch_001",
                                                            covers: "TURN#001-014"

USER#<sub>#CONV#conv_abc123                 TURN#00016      (recent turn, verbatim)
...

USER#<sub>#CONV_ARCHIVE#conv_abc123#batch_001  TURN#00001   (original paired turn)
USER#<sub>#CONV_ARCHIVE#conv_abc123#batch_001  TURN#00002   (original paired turn)
...
```

**GSI consideration:** a `GSI1` with `PK = USER#<sub>` and `SK = CONV#<conv_id>` enables "list all conversations for a user" without a table scan. Cheap to add from the start; project the META attributes only (sparse projection = minimal GSI cost).


### Why paired turns (not separate req/res items)

| | Paired | Separate |
|---|---|---|
| Logical model | Request + response are one unit | Pretends they're independent |
| Item count | Half | 2× |
| Timestamps | `request_ts` + `response_ts` on same item = latency metrics free | Compute delta across items |
| Summarization | "Summarize turns 1-14" is clean | Ambiguous orphans possible |

### Why separate items per turn (not turns-in-a-list)

| | Separate items | Single item with list |
|---|---|---|
| Size ceiling | None | 400KB hard limit (~50-100 turns) |
| Write cost | PutItem ~8 WRUs (constant) | UpdateItem rewrites entire item (grows with conversation; 16-50× more expensive) |
| Read cost | Identical (DDB charges on data volume) | Identical |
| Flexibility | Paginate, range query, archive subsets | All or nothing |

### Write order (decided: two-phase for durability)

1. User sends message → **PutItem** with `{request, request_ts, response: null}`.
2. Lambda streams full response via SSE.
3. After streaming completes → **UpdateItem** to fill `{response, response_ts, citations, tokens_in, tokens_out}`.

**Why:** if Lambda crashes mid-stream, the request is still recorded (shows user engaged; they saw partial response via SSE). No silent data loss. Update cost = one rewrite of ~12-15 WRUs per turn; acceptable for one conversation at a time.

### Summarization logic

**Rules:**
1. Only summarize raw turns. **Never re-summarize summary nodes.** Summaries accumulate, preserving the conversation arc.
2. **Trigger: token count of active raw turns exceeds ~15K tokens.** (Not item count — a conversation with 10 "yes/no" exchanges is tiny; one with 3 huge explanations is already eating context.)
3. **System prompt + paper text are EXCLUDED from the summarization budget.** Only user/assistant turn tokens count. System prompt and paper text are constant context; they don't signal "conversation is getting long."
4. **Non-destructive:** create summary turn → archive originals to `CONV_ARCHIVE#<conv_id>#<batch_id>`. Lossy for LLM context, lossless for user (always queryable by batch_id).

**Growth pattern:**
- Round 1: summarize turns 1-14 → summary_1 + archive batch_001.
- Round 2: summarize turns 16-34 (raw only, NOT summary_1) → summary_2 + archive batch_002.
- Active context: `[summary_1] + [summary_2] + ... + [recent verbatim turns]`.
- Multiple summaries preserve the arc. Re-summarizing them would flatten trajectory into mush.
- 10 summaries ≈ 2-5K tokens — noise-level vs. 40K paper text. No need to compress them.

### Streaming architecture (v0)

```
User sends message
  → Lambda Function URL invoked (SSE connection opened)
  → Query DDB: PK = CONV#<id> (returns META + summaries + recent turns)
  → GetObject S3: paper full text
  → Assemble: system prompt + paper text + [summaries in order] + [recent turns] + new request
  → PutItem: new turn with request, response: null
  → Call Anthropic streaming API
  → Forward chunks as SSE events to client
  → After stream completes: UpdateItem to fill response
  → Close SSE connection
```

Fully stateless Lambda. DDB IS the memory. Context reconstructed each invocation.

**v0 performance:**
- DDB Query: <10ms
- S3 GetObject: <50ms
- LLM first token: 1-3s (dominates)
- Total context: ~55K tokens (paper + history) ≈ $0.017/msg on Sonnet
- Well within 200K context window

---

## LLM Strategy

### The bake-off (first build step, first logged experiment)

Test before locking. ~8 papers × 3-4 models × tasks (triage/hook/digest). Blind-rank outputs.

```jsonc
{
  "experiment": "hook-bakeoff-v0",
  "paper_id": "2304.03442",
  "model": "sonnet",
  "task": "hook",
  "harness_version": "v0",
  "output": "<the generated hook>",
  "blind_rank": 1,
  "cost_tokens": 1234,
  "latency_ms": 890
}
```

**`harness_version`** makes this a repeatable thesis test: re-run later with better harness + worse model → rank improves? That's the "harness >> LLM" hypothesis, instrumented from day one.

### Likely split (to be confirmed by bake-off)

| Task | Model tier | Why |
|---|---|---|
| Triage (bulk: score hundreds of abstracts) | Cheaper / open (Gemma 3, Kimi, etc.) | ~90% of token volume; classification doesn't need Opus |
| Hooks + digests (the few papers you see) | Best available (Opus/Sonnet) | Make-or-break creative translation — this IS the product |

---

## Milestones

| Milestone | What ships | What it proves | AWS footprint |
|---|---|---|---|
| **M0** | Pipeline runs (Step Fn) → ~15 feed cards → scroll on phone | Do the hooks make me want to read? (beat Twitter) | S3, Step Fn, Lambda, Fargate, CloudFront, Cognito |
| **M1** | + engagement logging + nightly profile-learning + streaming chat (single-paper) | Feed gets smarter from my taps; I can ask questions | + DynamoDB, Lambda Function URL |
| **M2** | + library fills with rewrites; weekly brief; hypothesis tracking; tiered summaries | Becomes a research partner, not just a feed | Same infra, more pipeline logic |

---

## What's deferred (stubs exist, not implemented)

| Capability | When to add | Stub location |
|---|---|---|
| Spot instances | When compute bill justifies (~$10+/mo on digest) | `InterruptionHandler` protocol |
| Internal sources | When SSO auth is wired | `InternalSource` class |
| Area-wide Q&A (RAG) | When library has ~10+ papers | Conversation scope: "area" |
| Library-wide Q&A (RAG) | When library has ~20+ papers | Conversation scope: "library" |
| Weekly deep brief | After M1 (needs engagement data to synthesize) | Pipeline step |
| Vector embeddings | With area/library Q&A | New storage layer |

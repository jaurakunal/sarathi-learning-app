# 01 — Vision & Product Shape

## The reframe that defines the project

The reasons I don't read papers — lazy, deprioritized, too dense — are **all behavioral/delivery problems**, not informational ones. "Search arXiv and return a list" is the easy, fun 20% — and it would fail exactly the way my own good intentions have failed: the list would sit unread. So the product is **a chief of staff who makes me do it**, not a search engine. Finding papers is necessary but cheap. The hard, valuable parts:

1. **Friction removal** — comes to me, pre-digested, consumable in the gaps I actually have (phone, between meetings). 2–4 hrs/week means curation must be ruthless: 1 paper read deeply > 5 skimmed.
2. **Density translation** — progressive disclosure on every paper: one-line "why you care" → plain-language key ideas → deep technical version → Q&A on demand.
3. **Accountability** — cadence, gentle nudges, "you're 2 weeks out, here's a 10-min one to get back on the horse."

## Product decisions (settled)

| Decision | Choice |
|---|---|
| Repo | **Separate repo** (this one), not the Automations repo |
| Delivery | **Web UI**, frontend hosted on **S3 static website hosting**; real backend (API + DB + S3 for data/history). Mobile later. |
| Cadence | **Both** — a scrollable feed (daily micro-doses) *and* a weekly deep brief |
| The bar | The feed must **out-compete social media for my thumb**. A generic "top papers this week" list loses to that bar — personalization *is* the product. |
| Sources | Internal + external public (arXiv etc.) |
| Onboarding | A **conversation that runs until the bot is ≥90% confident** it understands my level (not time-boxed) |
| Stack | **Python** backend + pipeline, deployed AWS-native (see [05](05-research-spine.md) for the Rust reasoning) |

## The three depth tiers (how "abstracts vs full PDF" actually resolves)

The word "abstract" was overloaded. The real design is three tiers, each **earned**:

| Tier | Content | Job | Who sees it |
|---|---|---|---|
| **Triage** | author's own abstract + metadata | machine scans hundreds, ranks, picks a few | **machine only** — I never see raw abstracts |
| **Feed** | bot-generated **hook** + multi-level digest | the scrollable feed; provoke + translate | me |
| **Library** | **full text** of papers I engaged with | the COS brain: answer anything, find novel ideas, build my paper | me, on demand |

```
hundreds of papers → [author abstracts] → triage/rank → top few
   → bot reads deeper → [generated hook + multi-level digest] → feed card
   → I tap "read"/"go deep" → [full PDF pulled] → Library (full text, forever)
```

Author's abstract = the *filter input*. Bot's hook = the *feed output*. Full text = the *library*. The two stores (discovery vs. library) are permanent and serve different jobs; engagement is the signal that graduates a paper from one to the other.

## The hook is the product

Researchers write abstracts for *other experts* — dense, dry, no hook. Translating that gap **is** the COS's core job. The feed hook is not a summary — it's a **provocation**: it earns the next 5 seconds by creating an itch (a question I now need answered), anchored to my level + my other interests + the thread connecting my areas.

**Critical counterweight:** a hook-generator is also a hype-generator. The failure mode is an exciting, shallow "research tabloid" that oversells mediocre papers and destroys trust. So hook-strength and honesty are engineered as a **pair**: the bot privately assesses "is this worth my scarce 2–4 hrs?" and only hooks hard on papers that earn it. Provocative **and** grounded, or it fails.

## Architecture sketch (conceptual)

```
Knowledge State (per area: concept graph + proficiency)   ← the brain (v0: profile doc + runtime LLM reasoning, NOT a graph DB)
        │
   Curator (internal + arXiv/external, quality-filtered)  ← finds + ranks
        │
   Digester (multi-level explanations, grounded)          ← kills density
        │
   Delivery + Coach (cadence, nudges, right-sized)        ← kills laziness
        │
   Sounding board (on-demand Q&A at any altitude)         ← multi-level discussion
        │
   [phase 2] Synthesis → influence artifacts + research gaps + my own paper
```

The "brain" does **not** start as a knowledge-graph engineering project. v0 = a **profile document the LLM reads before curating and writes back to after I engage** + runtime reasoning. Earn the fancy graph later, only if the simple version proves it's needed.

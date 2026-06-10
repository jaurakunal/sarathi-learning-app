# 02 — Scope & Design Principles

## The scope decision: build it for one user (me)

I was torn between building something **hyper-personalized to me** vs. something **generic/reusable for others at work** (which I associate with senior/principal SDE signal). I named my own failure mode in the same breath: *"I tend to go down rabbit holes trying to build something that will work for everyone."*

**Decision: build it for ONE user (me). Hyper-personal.** Engineer the internals clean (areas as *data*, generic schema — not hardcoded), but do **not** pre-build multi-tenancy, auth, or stranger-onboarding. Generalize only if/when a real second user appears.

### Why this is the *more* senior choice, not the lesser one

1. **"Generic enough for others" is discovered, not designed.** Platforms that define a senior/principal eng start as someone scratching their own specific itch and *then* generalizing once the itch is real. With no real second user, the abstraction has nothing to say "no" to it — so the rabbit hole is bottomless. **One concrete user ends the rabbit hole.**
2. **The principal-defining skill is judgment about what NOT to build** — ruthless scoping, resisting gold-plating. A generic platform nobody asked for reads as "couldn't scope." The promo-positive story *requires* the personal version first: *"I built it, used it daily, it changed my habit — here's the data — now I see the general shape and I'm extracting the reusable core."* You can't tell that story backwards.
3. **Generic-from-day-one is more expensive AND worse for everyone.** Multi-tenant auth, isolation, configurable everything = months before I read one paper. And a tool for "everyone" is shaped for no one.

**The reconciliation:** *Scope for one user. Engineer the internals clean.* The only generalization paid up front is a clean generic data model (cheap, just good engineering). Everything else waits for a real second human.

> **Guardrail:** When "but what if other people want to…" / configurability for hypothetical users / multi-tenant concerns surface mid-build — STOP and name it as the rabbit hole. Refuse to answer the generic-vs-personal question in the abstract; let an actual second user decide it.

## Don't over-index on stated interests

The stated areas of interest are a **seed, not a spec.** Interests change (I'm also drawn to physics & spirituality). So the system is **generic**: areas/categories are *data*, not hardcoded buckets. No `if area == "memory"` anywhere. New areas (physics, spirituality, learning Rust) drop in as data records with zero code change. The insight that "my areas are really one bigger goal" is something the **LLM derives at runtime** from the profile — not a fact baked into code.

## The principles, in one place

1. **Built for one user (me).** Clean generic data model; zero multi-tenant cost up front.
2. **The hook is the product.** Raw abstracts never reach me; provoke + translate, but honest — never a research tabloid.
3. **Sharp mirror, not hype man.** Never flatter, never inflate what I built, never call my ideas "novel/brilliant." I correct overclaims reflexively and find inflation grating — it also degrades my self-model. Credit at *exactly* the right scope. Distinguish what's genuinely mine from ideas I encountered elsewhere.
4. **Route around math, never gate on it.** Translate to intuition/analogy; equations are optional tap-to-reveal, never required, never pushed.
5. **Don't over-index on stated interests.** Areas are data. Interests change.
6. **Truth-telling over motivation.** Including the honorable "this might not be possible" — a real, valid ending (see [05](05-research-spine.md)).

## Stack decision: Python now, Rust later (and deliberately)

I'm most comfortable in Python; my team is migrating everything to Rust (I have zero Rust knowledge and need to learn it). **Decision: do NOT build v0 in Rust.**

- Learning Rust *while* building my first Rust thing *while* doing heavy LLM/glue work = the biggest non-shipping risk, and it reopens the rabbit hole.
- This project is mostly **glue/IO** (LLM calls, PDF parsing, arXiv, JSON, DB) — exactly where Rust's strengths buy nothing and Python is fastest. Wrong shape to learn Rust on.
- The two goals (ship a habit tool / learn Rust for the team) are separable; forcing them into one artifact serves neither.

**Better Rust path:** (a) make "learn Rust" an *area of interest inside the COS itself* — the tool teaches me the thing I need for work (perfect dogfood); and (b) later, as a deliberate exercise, rewrite **one hot path** (e.g. a concurrent paper-fetcher/indexer) in Rust callable from Python — a problem Rust is actually built for, with a working Python reference to check against.

> **Principle:** Don't let the learning goal hijack the shipping goal.

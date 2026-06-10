# 04 — My Learner Profile

Captured during the onboarding interview (June 2026). This becomes the seed input for `profile.json`.

## Profile type: practitioner with zero theory vocabulary

I build fluently but have never read a paper end-to-end and have little academic-term vocabulary. I do the things, then lack the formal names — nearly the opposite of the typical "wants to read papers" academic-adjacent person.

**Implication for the bot:** its highest-value move is *"here's the formal name + the theory behind the thing you already built by instinct"* — connecting my tacit/applied knowledge to the literature. That's a satisfying kind of learning and it lands well on me.

## Evidence of applied level (real, shipped things)

- A **person-cloning prototype**: scrapes LinkedIn + other public info (a video of them speaking, an article they wrote) → runs it through a prompt that builds a psychological profile → holds a mock conversation as that person. Chris Voss negotiation techniques baked in. A test user said the responses were very much what she'd have said. **I arrived at this cold** — independent of the literature; only found the Stanford "Generative Agents" work afterward (and *still haven't read it*). → strong independent product intuition.
- A **journalist-similarity pipeline** (precise scope, my own correction): used existing APIs to scrape articles for given outlets → embedding LLM → vectors in an **S3 Vector bucket** → vector query for similar journalists → stored relationships in **Neo4j**. So: comfortable *wiring* embeddings + vector search + graph DB into a working system at the orchestration/integration level — *not* implementing ML from scratch.
- A free **security-audit tool for vibe coders**: uses LLMs to model attacks, find vulnerabilities, and fix them (ties to the red/blue interest).

## Theory vocabulary check

| Term | Status |
|---|---|
| Retrieval-augmented (RAG) | **Very familiar** — built one |
| "Memory stream" | Guessed essentially correctly (stream of synthesized/inferred memory units) |
| "Reflection" (Generative Agents sense) | Didn't know — but **already trying to build it** in a product. Now explained. |
| Papers finished end-to-end | **Zero.** Downloaded a fair few; bounce off when density/math ramps (happens fast) |

## Math: route around, do not gate

Pure aversion — self-describes as *"I never learned this math, the symbols are foreign."* Engineering degree ~20 years ago, unused since. Recognizes **none** of 𝔼[·], ∇, softmax, KL divergence. Finds math *"fascinating and scary"* → there's latent appetite if it's made unintimidating.

**Rule:** the bot translates everything to intuition/analogy; math is **optional progressive disclosure** (tap-to-reveal), never a gate, never pushed. Long-term option: teach one concept at a time, pull-only.

## What sends me to a paper (the need to satisfy)

To **understand a concept well enough to apply it** to what I'm building right now — *not* comprehension for its own sake. The bot must satisfy "can I use this?" without the density wall. **Lead hooks with the applied angle; theory is what gets translated down.** The build is the destination, not the paper.

## Active product context driving the interests

I've been building a system that stores a person's conversations/history/story and builds human-like memory **connections** — recalling the right story, linking someone's background to a piece of content or a podcast they heard — to write content/emails as them. This *is* reflection + associative memory; it's the live wire connecting the "person-cloning," "human mental models → agent," and "human memory models" interests.

## How I correct things (trait the bot must respect)

I reflexively correct credit I haven't earned — I scoped "built a RAG system" down to "wired existing APIs into a pipeline," and declined credit for the contemplative-memory framing because it came from an article. **Do not flatter me, do not call my ideas novel, do not inflate what I built.** Be a sharp, accurate mirror. (See principle #3 in [02](02-scope-and-principles.md).)

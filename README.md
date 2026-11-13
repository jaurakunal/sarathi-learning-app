# Sārathi — a Chief of Research Staff

*Sārathi (सारथि)* — Sanskrit for **charioteer**: the one who holds the reins and guides. Most famously Krishna as Pārtha-sārathi, Arjuna's charioteer in the Bhagavad Gita — who counsels, steers, and tells hard truths at the moment of doubt, but does not fight the war for him. (In the Katha Upanishad: the intellect is the charioteer, the mind the reins, the senses the horses — a disciplined mind steering toward clarity.) That is exactly this project's charter: it guides and tells the honest thing — including *"this can't be done"* — but I do the building.

A personal "chief of research staff" that makes me **actually read research** — not a paper search engine. It comes to me, pre-digested, in a form I'll consume in the gaps I actually have, keeps my multi-year obsession warm, and accumulates the raw material for a paper of my own.

## The problem it solves

I want to read more research but don't, for three behavioral reasons: too lazy, it gets deprioritized, and papers are too dense. None of these is "I can't find good papers." So the center of gravity is **friction removal + density translation + accountability**, not search. Finding papers is necessary but cheap; making me read them is the hard, valuable part.

## What it is

A scrollable feed (web UI) I'd open *instead of* brain-numbing social media, backed by a model of where I am in each area, that:

- **Translates** dense, expert-written papers into provocative, honest, personalized hooks (I never see a raw abstract).
- **Curates ruthlessly** for a 2–4 hrs/week budget — 1 paper read deeply beats 5 skimmed.
- **Goes to any depth on demand** — hook → plain-language gist → deep version → ask-it-anything.
- **Remembers everything I engage with** as a full-text library, so it can answer any question later and find novel ideas.
- **Reads everything through my hypothesis** and accumulates material toward my own paper.

## Guiding principles (the non-negotiables)

1. **Built for one user (me).** Hyper-personal. Clean generic data model internally, but zero multi-tenant cost paid up front. Generalize only if a real second user appears. See [docs/02-scope-and-principles.md](docs/02-scope-and-principles.md).
2. **The hook is the product.** Raw abstracts never reach me; the bot translates the expert→me gap. Hooks provoke, but are honest — never a research tabloid.
3. **Sharp mirror, not hype man.** Never flatter, never inflate what I built or claim ideas are "novel." Truth-telling over motivation — including "this might not be possible."
4. **Route around math, never gate on it.** Translate to intuition; equations are optional tap-to-reveal.
5. **Don't over-index on stated interests.** Areas are *data*, not code. Interests change.

## Status

Working end to end for a small number of users: nightly discovery → triage →
digest pipeline, personalised feed, grounded chat over paper full text, an
onboarding interview, and an engagement-driven learning loop. Still a personal
project — expect rough edges and opinionated defaults.

## Repository layout

| Path | What lives there |
|---|---|
| [`backend/`](backend/) | Python Lambda + container code: `api/` handlers, the nightly `pipeline/`, paper `sources/`, `research/` chat, `eval/` harness, `monitoring/`, `shared/` utilities |
| [`frontend/`](frontend/) | React + TypeScript + Vite single-page app |
| [`infra/`](infra/) | AWS CDK (TypeScript) stack: DynamoDB, S3, Cognito, Step Functions, API Gateway, AppSync, CloudFront |
| [`scripts/`](scripts/) | Eval runners, backfills, migrations, and integration tests against a deployed stack |
| [`tests/`](tests/) | Backend unit tests (mirrors `backend/`) |
| [`docs/`](docs/) | Design docs, eval reports (`docs/evals/`), and operational runbooks (`docs/runbooks/`) |

## Quick start

Requires Python 3.12+, Node 22+, and (to deploy) an AWS account with
[CDK bootstrapped](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html)
and Amazon Bedrock model access.

```bash
# Backend unit tests
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
make test

# Deploy the stack to your own account
cd infra && npm ci && npx cdk deploy

# Frontend
cd frontend && npm ci
cp .env.example .env.local    # fill in values from the stack outputs
npm run dev
```

Scripts and runbooks use `123456789012` as a placeholder AWS account ID;
substitute your own (most scripts also accept `BUCKET_NAME` / `SARATHI_BUCKET`
environment overrides).

## Docs

- [01 — Vision & Product Shape](docs/01-vision-and-product-shape.md)
- [02 — Scope & Design Principles](docs/02-scope-and-principles.md)
- [03 — Onboarding Interview Methodology](docs/03-onboarding-interview-methodology.md)
- [04 — My Learner Profile](docs/04-learner-profile.md)
- [05 — The Research Spine (the real thesis)](docs/05-research-spine.md)
- [06 — Architecture Blueprint](docs/06-architecture-blueprint.md)
- [07 — M0 Build Plan](docs/07-m0-build-plan.md)
- [08 — M0 Frontend Plan](docs/08-m0-frontend-plan.md)
- [Model evaluation reports](docs/evals/final-report.md)
- [Operational runbooks](docs/runbooks/README.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
Report security issues per [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)

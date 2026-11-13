# Contributing to Sārathi

Thanks for your interest. Sārathi started as a single-user project, so expect
rough edges; issues and pull requests are welcome.

## Getting set up

```bash
# Backend (Python 3.12+)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Frontend
cd frontend && npm ci && cp .env.example .env.local

# Infrastructure (AWS CDK, TypeScript)
cd infra && npm ci
```

## Running checks

| What | Command |
|---|---|
| Backend unit tests (no network) | `make test` |
| Frontend tests | `cd frontend && npm test` |
| Frontend lint | `cd frontend && npm run lint` |
| CDK synth | `make synth` |

Integration tests (`make integration-test`, `make api-test`, `make full-test`)
run against a deployed stack in your own AWS account and are not required for
a pull request.

The optional pre-commit hook in `.githooks/` runs the unit and integration
tests; enable it with `git config core.hooksPath .githooks`.

## Pull requests

- Keep each PR to one logical change, with tests for behaviour changes.
- Describe what changed and why; link the issue if there is one.
- Never commit credentials, account IDs, or `.env.local` files.

## Reporting bugs and security issues

Use GitHub issues for bugs and feature requests. For security problems, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.

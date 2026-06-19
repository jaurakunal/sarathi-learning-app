.PHONY: help install test integration-test test-all lint deploy synth build-backend build-frontend

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies
	pip install -r requirements.txt
	cd infra && pip install -r requirements.txt

test: ## Run unit tests (fast, no network)
	python -m pytest tests/ -v

integration-test: ## Run full pipeline integration test (hits real AWS)
	AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python scripts/integration_test.py

api-test: ## Run API integration test (validates deployed endpoints + CORS)
	AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python scripts/api_integration_test.py

full-test: ## Run comprehensive integration test (API + pipeline + learn)
	AWS_PROFILE=poc AWS_DEFAULT_REGION=us-east-1 python scripts/full_integration_test.py

test-all: test api-test full-test ## Run unit tests + all integration tests

lint: ## Run linting
	python -m ruff check backend/ infra/

build-backend: ## Package backend for deployment
	@echo "Backend packaging — handled by CDK asset bundling"

build-frontend: ## Build frontend SPA
	cd frontend && npm run build

synth: ## Synthesize CDK CloudFormation template
	cd infra && cdk synth

deploy: ## Deploy infrastructure via CDK
	cd infra && cdk deploy --require-approval never

diff: ## Show CDK diff against deployed stack
	cd infra && cdk diff

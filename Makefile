# Prepay developer commands. Every target is offline and synthetic unless stated otherwise.
# Windows without make: run the quoted `uv run ...` commands directly (see README).

UV ?= uv
RUN := $(UV) run --frozen

.DEFAULT_GOAL := help
.PHONY: help setup check lint fmt typecheck test test-finance synth

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install the pinned Python environment from uv.lock
	$(UV) sync --frozen

check: lint typecheck test ## Full offline synthetic quality gate (CI runs exactly this)

lint: ## Ruff lint and format check
	$(RUN) ruff check src tests
	$(RUN) ruff format --check src tests

fmt: ## Apply Ruff formatting and safe fixes
	$(RUN) ruff format src tests
	$(RUN) ruff check --fix src tests

typecheck: ## mypy --strict over src/prepay
	$(RUN) mypy

test: ## All tests, including slow mutation checks
	$(RUN) pytest

test-finance: ## Finance suite with >=90% line+branch coverage gate on prepay.finance
	$(RUN) pytest tests/financial --cov=prepay.finance --cov-branch --cov-report=term-missing --cov-fail-under=90

synth: ## Generate the fictional CI dataset into data/synthetic/ci
	$(RUN) prepay synth --preset ci --out data/synthetic/ci

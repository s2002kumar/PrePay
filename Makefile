# Prepay developer commands. Every target is offline and synthetic unless stated otherwise.
# Windows without make: run the quoted `uv run ...` commands directly (see README).

UV ?= uv
RUN := $(UV) run --frozen
# Synthetic world for the demo bundle: ci (~6k loans, fast) or dev (~47k loans; README screenshots).
DEMO_PRESET ?= ci

.DEFAULT_GOAL := help
.PHONY: help setup check lint fmt typecheck test test-finance synth data-lock benchmark research seal evaluate-lockbox synthetic-study demo-bundle demo publication-check

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-14s %s\n", $$1, $$2}'

setup: ## Install the pinned Python environment from uv.lock
	$(UV) sync --frozen

check: lint typecheck test ## Full offline synthetic quality gate (CI runs exactly this)

lint: ## Ruff lint/format check and SQLFluff on the dbt project
	$(RUN) ruff check src tests
	$(RUN) ruff format --check src tests
	$(RUN) sqlfluff lint transform/models transform/tests

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

data-lock: ## Verify private source files against configs/data.lock.json (local research only)
	$(RUN) prepay data-lock verify --raw-dir data/raw --lock configs/data.lock.json

benchmark: ## Measure pipeline wall time, peak RSS and throughput (synthetic dev preset)
	$(RUN) prepay benchmark --preset dev --work-dir scratch/benchmark --report-dir reports/benchmarks

# ---- private research (real data; never run in public CI). RUN_DIR=artifacts/runs/<run_id>
DATA_ROOT ?= data
LOCK ?= configs/data.lock.json

research: ## Local-only: verify lock, ingest, transform, train (real or synthetic data)
	$(RUN) prepay data-lock verify --raw-dir $(DATA_ROOT)/raw --lock $(LOCK)
	$(RUN) prepay ingest --raw-dir $(DATA_ROOT)/raw --lock $(LOCK) --data-root $(DATA_ROOT)
	$(RUN) prepay transform --data-root $(DATA_ROOT) --lock $(LOCK)
	$(RUN) prepay train --data-root $(DATA_ROOT) --lock $(LOCK) --out artifacts/runs

seal: ## Freeze a run before holdout access: make seal RUN_DIR=artifacts/runs/<run_id>
	$(RUN) prepay seal --run $(RUN_DIR)

evaluate-lockbox: ## One-shot sealed holdout evaluation: make evaluate-lockbox RUN_DIR=...
	$(RUN) prepay evaluate-lockbox --run $(RUN_DIR) --data-root $(DATA_ROOT) --lock $(LOCK)

# ---- end-to-end synthetic study (public-safe): generate -> lock -> ingest -> dbt -> train -> seal -> lockbox
STUDY := data/synthetic/study
synthetic-study: ## Full research pipeline on fictional data, including the one-shot lockbox
	$(RUN) prepay synth --preset ci --out $(STUDY)/source
	$(RUN) prepay data-lock create --raw-dir $(STUDY)/source/raw --synthetic-manifest $(STUDY)/source/manifest.json --out $(STUDY)/data.lock.json
	$(RUN) prepay ingest --raw-dir $(STUDY)/source/raw --lock $(STUDY)/data.lock.json --data-root $(STUDY)
	$(RUN) prepay transform --data-root $(STUDY) --lock $(STUDY)/data.lock.json
	$(RUN) prepay train --data-root $(STUDY) --lock $(STUDY)/data.lock.json --out $(STUDY)/runs --truth-dir $(STUDY)/source/truth
	$(RUN) prepay seal --run "$$(ls -d $(STUDY)/runs/*/ | tail -1)"
	$(RUN) prepay evaluate-lockbox --run "$$(ls -d $(STUDY)/runs/*/ | tail -1)" --data-root $(STUDY) --lock $(STUDY)/data.lock.json

demo-bundle: ## Build the fictional demo bundle (sealed synthetic-trained run) into build/demo
	$(RUN) prepay demo build --out build/demo --preset $(DEMO_PRESET)

demo: ## Serve the demo API + web UI on http://127.0.0.1:8000 (fictional data only)
	$(RUN) prepay serve --bundle build/demo --web-dist web/dist

publication-check: ## Scan tracked files, history, web build and demo bundle for restricted content
	$(RUN) prepay publication-check --history --tree web=web/dist --tree demo=build/demo

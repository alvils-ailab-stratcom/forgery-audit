UV ?= uv
export UV_PROJECT_ENVIRONMENT := $(CURDIR)/.venv
DATA ?= data
OUTPUT ?= results/audit

.PHONY: install lint format types test check audit build analyze reports
install:
	$(UV) sync --locked
lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .
types:
	$(UV) run ty check src
test:
	$(UV) run pytest -q --cov=forgery_audit --cov-report=term-missing --cov-report=xml
check: lint types test
	$(UV) lock --check
audit:
	$(UV) audit --locked
build:
	$(UV) build
# Live run: uploads new or option-changed files, polls, asks Detect Intelligence, writes PDF and Markdown.
analyze:
	$(UV) run forgery-audit "$(DATA)" --output "$(OUTPUT)"
# Offline: regenerate analysis, PDF and Markdown (reports/*.lv.md, atzinums.lv.md) from saved payloads.
reports:
	$(UV) run forgery-audit "$(DATA)" --output "$(OUTPUT)" --offline

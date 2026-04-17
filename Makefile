.PHONY: install install-local uninstall-local routing overlap lint fmt fmt-check typecheck check test test-integration

install:
	uv sync

install-local:
	uv tool install --force .

uninstall-local:
	uv tool uninstall claude-marketplace-evaluator

routing:
	uv run cme routing

overlap:
	uv run cme overlap

lint:
	uv run ruff check src/ tests/

fmt:
	uv run ruff format src/ tests/

fmt-check:
	uv run ruff format --check src/ tests/

typecheck:
	uv run mypy

check: lint fmt-check typecheck

test:
	uv run pytest

test-integration:
	uv run pytest -m integration tests/integration/

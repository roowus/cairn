.PHONY: install dev install-global run repl test lint typecheck docs-import ollama clean

install:        ## Install core deps into .venv
	uv sync

dev:            ## Install core + dev deps
	uv sync --extra dev

install-global: ## Put `cairn` on PATH (editable, like pi/claude) + seed ~/.cairn/.env
	uv tool install --editable --force .
	@mkdir -p $(HOME)/.cairn
	@if [ -f .env ]; then cp .env $(HOME)/.cairn/.env && chmod 600 $(HOME)/.cairn/.env; \
		elif [ -f .env.example ] && [ ! -f $(HOME)/.cairn/.env ]; then \
			cp .env.example $(HOME)/.cairn/.env && chmod 600 $(HOME)/.cairn/.env; fi
	@echo "Installed: $$(command -v cairn)  ($$(cairn --version 2>/dev/null || echo ok))"

run:            ## Run the REPL
	uv run cairn

repl: run

test:           ## Run the unit test suite (no network)
	uv run pytest -m "not network"

test-net:       ## Run tests including real free-API calls
	uv run pytest -m network

lint:           ## Lint with ruff
	uv run ruff check .

format:         ## Auto-format with ruff
	uv run ruff format .

typecheck:      ## Type-check with mypy
	uv run mypy src

docs-import:    ## Convert ~/Downloads research RTFs into docs/research/*.md
	bash scripts/import_research_docs.sh

ollama:         ## Pull a local model for the no-key smoke test
	bash scripts/bootstrap_ollama.sh

clean:          ## Remove build/test artifacts
	rm -rf .mypy_cache .ruff_cache .pytest_cache build dist *.egg-info

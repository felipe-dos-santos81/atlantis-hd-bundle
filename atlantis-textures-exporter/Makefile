# Makefile for atlantis-textures-exporter — SCUMM v5 background extraction
# Pipeline: env → extract → verify
SERVICE = atlantis-textures-exporter

# Variables
VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
GAME ?= $(HOME)/Documents/Indiana Jones® and the Fate of Atlantis™.app/Contents/Resources/game/game
OUT ?= out

.PHONY: help install extract test clean

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — SCUMM v5 background extraction\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [game=\"<game dir>\" out=<dir>]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and install Pillow + pytest
	@if [ ! -d "$(VENV_DIR)" ]; then \
		python3 -m venv $(VENV_DIR); \
		$(PIP) install -U pip; \
		$(PIP) install -U pillow pytest; \
	fi
	@echo "Environment ready."

# ── Extract ──────────────────────────────────────────────────────────────────

extract: install ## Extract all 96 room backgrounds (override: make extract game=/path out=dir)
	$(PYTHON) extract.py --game "$(GAME)" --out "$(OUT)"

# ── Development ──────────────────────────────────────────────────────────────

test: install ## Run the pytest suite
	$(PYTHON) -m pytest -q

clean: ## Remove .venv, generated output, and caches
	rm -rf $(VENV_DIR) $(OUT)
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleanup complete."

# Makefile for atlantis-textures-importer — HD backgrounds in the GOG app
# Pipeline: env → build → validate → install (→ verify, uninstall)
SERVICE = atlantis-textures-importer

# Variables
VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
EXPORTER = ../atlantis-textures-exporter
IMPORTER = PYTHONPATH=.:$(EXPORTER) $(PYTHON) -m importer
ai ?= $(HOME)/Documents/Indiana Jones and the Fate of Atlantis-ai
app ?= $(HOME)/Documents/Indiana Jones® and the Fate of Atlantis™.app
ARGS = --ai "$(ai)" --app "$(app)"

.PHONY: help env build patch validate install uninstall verify test test-engine clean

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — HD backgrounds in the GOG app\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [ai=\"<AI folder>\" app=\"<game .app>\"]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

env: ## Create .venv and install Pillow
	@if [ ! -d "$(VENV_DIR)" ]; then \
		python3 -m venv $(VENV_DIR); \
		$(VENV_DIR)/bin/pip install -U pip pillow; \
	fi
	@echo "Environment ready."

# ── Engine ───────────────────────────────────────────────────────────────────

build: ## Build the patched ScummVM into vendor/scummvm/ScummVM.app
	./scripts/build_scummvm.sh

patch: ## Save the edits in vendor/scummvm to patches/scumm-hd.patch
	git -C vendor/scummvm diff > patches/scumm-hd.patch

# ── App ──────────────────────────────────────────────────────────────────────

validate: env ## Check every AI background against the game's rooms
	$(IMPORTER) validate $(ARGS)

install: env ## Install the patched ScummVM and the HD backgrounds into the app
	$(IMPORTER) install $(ARGS)

uninstall: env ## Restore the app's original ScummVM and configfile
	$(IMPORTER) uninstall $(ARGS)

verify: env ## Check the installed engine and HD files
	$(IMPORTER) verify $(ARGS)

# ── Development ──────────────────────────────────────────────────────────────

test: env ## Run the Python test suite
	PYTHONPATH=.:$(EXPORTER) $(PYTHON) -m unittest discover -s tests

test-engine: ## Build and run the compositor core's standalone tests
	mkdir -p build
	$(CXX) -std=c++17 -Wall -Wextra -Werror -DHD_COMPOSE_STANDALONE -Iengine \
		engine/scumm/hd_compose.cpp engine/test_hd_compose.cpp -o build/test_hd_compose
	./build/test_hd_compose

clean: ## Remove .venv, build/ and caches (keeps vendor/)
	rm -rf $(VENV_DIR) build
	find . -type d -name "__pycache__" -not -path "./vendor/*" -exec rm -rf {} +
	@echo "Cleanup complete."

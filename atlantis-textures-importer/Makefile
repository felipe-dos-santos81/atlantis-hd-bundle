# Makefile for atlantis-textures-importer — HD backgrounds in the GOG app
# Targets are numbered by pipeline stage:
#   install → 1 engine-build → 2 hd-validate → 3 hd-install → 4 hd-verify (→ hd-uninstall)
SERVICE = atlantis-textures-importer

# Variables
VENV_DIR = .venv
PYTHON = PYTHONPATH=$$(pwd):$$(pwd)/../atlantis-textures-exporter $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
# Paths default to ~/Documents (importer/cli.py); override with ai="..." app="..."
PATHS = $(if $(ai),--ai "$(ai)") $(if $(app),--app "$(app)")

.PHONY: help install clean \
        engine-build engine-patch \
        hd-validate hd-install hd-verify hd-uninstall \
        test test-engine

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — HD backgrounds in the GOG app\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [ai=\"<AI folder>\" app=\"<game .app>\"]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

install: ## Initialize .venv and install Pillow
	@if [ ! -d "$(VENV_DIR)" ]; then \
		python3 -m venv $(VENV_DIR); \
		$(PIP) install -U pip; \
		$(PIP) install -U pillow; \
	fi; \
	echo "Environment setup complete."

clean: ## Remove .venv, build/ and caches (keeps vendor/)
	rm -rf $(VENV_DIR) build
	find . -type d -name "__pycache__" -not -path "./vendor/*" -exec rm -rf {} +
	@echo "Cleanup complete."

# ── Stage 1 · Engine (patched ScummVM v2026.3.0) ─────────────────────────────

engine-build: ## [STEP 1] Build the patched ScummVM into vendor/scummvm/ScummVM.app
	./scripts/build_scummvm.sh

engine-patch: ## Save edits to existing ScummVM files in vendor/scummvm to patches/scumm-hd.patch
	git -C vendor/scummvm diff > patches/scumm-hd.patch

# ── Stages 2–4 · HD backgrounds in the app ───────────────────────────────────

hd-validate: install ## [STEP 2] Check every AI background against the game's rooms
	$(PYTHON) -m importer validate $(PATHS)

hd-install: install ## [STEP 3] Install the patched ScummVM and the HD backgrounds (quit the game first)
	$(PYTHON) -m importer install $(PATHS)

hd-verify: install ## [STEP 4] Check the installed engine and HD files
	$(PYTHON) -m importer verify $(PATHS)

hd-uninstall: install ## Restore the app's original ScummVM and configfile
	$(PYTHON) -m importer uninstall $(PATHS)

# ── Development ───────────────────────────────────────────────────────────────

test: install ## Run the Python unit test suite
	$(PYTHON) -m unittest discover -s tests

test-engine: ## Build and run the compositor core's standalone tests
	mkdir -p build
	$(CXX) -std=c++17 -Wall -Wextra -Werror -DHD_COMPOSE_STANDALONE -Iengine \
		engine/scumm/hd_compose.cpp engine/test_hd_compose.cpp -o build/test_hd_compose
	./build/test_hd_compose

# Makefile for atlantis-hd-bundle — the three-stage HD background pipeline
#
#   exporter   extract the 96 room backgrounds from your own copy of the game
#   enhancer   repaint them at 4x through ComfyUI (caption → batch → review → verify)
#   importer   build a patched ScummVM and install it with the HD backgrounds
#
# Every target is prefixed by its project; install/test/clean run all three.
# Run `make help` for the full list.

EXPORTER_DIR = atlantis-textures-exporter
ENHANCER_DIR = atlantis-texture-enhancement
IMPORTER_DIR = atlantis-textures-importer
VENV_DIR = .venv
PY = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip

EXPORTER_RUN = cd $(EXPORTER_DIR) && $(PY)
ENHANCER_RUN = cd $(ENHANCER_DIR) && $(PY)
IMPORTER_RUN = cd $(IMPORTER_DIR) && PYTHONPATH=../$(EXPORTER_DIR) $(PY)

# ── Exporter arguments ───────────────────────────────────────────────────────

GAME ?= $(HOME)/Documents/Indiana Jones® and the Fate of Atlantis™.app/Contents/Resources/game/game
OUT ?= out

# ── Enhancer arguments, e.g. make enhancer-batch room="1 58" workflow=qwen-image-2.1-i2i force=1 ──

room ?=
src ?=
dst ?=
force ?=
memcheck ?= 1
strength ?=
workflow ?=
FORCE_ARG = $(if $(force),--force)
ARGS = $(foreach r,$(room),--room $(r)) $(if $(src),--src "$(src)") $(if $(dst),--dst "$(dst)")
BATCH_ARGS = $(if $(filter 0,$(memcheck)),--no-memory-check) $(if $(strength),--match-strength $(strength)) \
             $(if $(workflow),--workflow $(workflow)) $(FORCE_ARG)

# ── Importer arguments ───────────────────────────────────────────────────────

PATHS = $(if $(ai),--ai "$(ai)") $(if $(app),--app "$(app)")

.PHONY: help install test clean \
        exporter-install exporter-extract exporter-test exporter-clean \
        enhancer-install enhancer-server enhancer-caption enhancer-dry-run enhancer-batch \
        enhancer-review enhancer-verify enhancer-check enhancer-test enhancer-clean \
        importer-install importer-engine-build importer-engine-patch \
        importer-hd-validate importer-hd-install importer-hd-verify importer-hd-uninstall \
        importer-test importer-test-engine importer-clean

help: ## Print this help message
	@printf '\033[01;32matlantis-hd-bundle\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make <target> [VAR=value ...]\n"
	@for g in Exporter:exporter Enhancer:enhancer Importer:importer; do \
		printf "\n\033[33m%s\033[0m\n" "$${g%%:*}"; \
		grep -E "^$${g##*:}-[-a-zA-Z0-9_\.\/]+:.*?## .*$$" $(MAKEFILE_LIST) | \
			awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}'; \
	done
	@printf "\n\033[33mAll\033[0m\n"
	@grep -E '^(install|test|clean|help):.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}'

# ── The whole bundle ─────────────────────────────────────────────────────────

install: exporter-install enhancer-install importer-install ## Create all three virtualenvs

test: exporter-test enhancer-test importer-test importer-test-engine ## Run every test suite

clean: exporter-clean enhancer-clean importer-clean ## Clean all three projects

# ── Exporter · extract the room backgrounds ──────────────────────────────────

exporter-install: ## Create exporter/.venv and install Pillow + pytest
	@cd $(EXPORTER_DIR) && if [ ! -d "$(VENV_DIR)" ]; then \
		python3 -m venv $(VENV_DIR); \
		$(PIP) install -U pip; \
		$(PIP) install -U pillow pytest; \
	fi
	@echo "exporter environment ready."

exporter-extract: exporter-install ## Extract all 96 room backgrounds (GAME=, OUT=)
	$(EXPORTER_RUN) extract.py --game "$(GAME)" --out "$(OUT)"

exporter-test: exporter-install ## Run the exporter pytest suite
	$(EXPORTER_RUN) -m pytest -q

exporter-clean: ## Remove exporter .venv, output and caches
	cd $(EXPORTER_DIR) && rm -rf $(VENV_DIR) "$(OUT)" .pytest_cache && \
		find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "exporter cleanup complete."

# ── Enhancer · repaint the rooms at 4x ───────────────────────────────────────

enhancer-install: ## Create enhancer/.venv with Pillow, PyYAML and numpy (re-running is safe)
	@cd $(ENHANCER_DIR) && { [ -x "$(PY)" ] || python3 -m venv $(VENV_DIR); }
	@cd $(ENHANCER_DIR) && { $(PY) -c 'import PIL, yaml, numpy' 2>/dev/null || \
		$(PIP) install -q "pillow>=10" "pyyaml>=6" "numpy>=1.26"; }

enhancer-server: ## Start ComfyUI on :8188 from ~/ComfyUI (override COMFY_DIR)
	cd $(ENHANCER_DIR) && ./run_server.sh

enhancer-caption: enhancer-install ## [STEP 1] Caption scene/insert rooms with vLLM into rooms.yaml (room=, force=1)
	cd $(ENHANCER_DIR) && ./run_batch.sh caption $(ARGS) $(FORCE_ARG)

enhancer-dry-run: enhancer-install ## [STEP 2a] Preview batch's plan, without touching ComfyUI (room=, workflow=, strength=, force=1)
	cd $(ENHANCER_DIR) && ./run_batch.sh batch --dry-run $(ARGS) $(BATCH_ARGS)

enhancer-batch: enhancer-install ## [STEP 2] Render via ComfyUI into data/rooms-ai; stop vLLM first (room=, workflow=, strength=, memcheck=0, force=1)
	cd $(ENHANCER_DIR) && ./run_batch.sh batch $(ARGS) $(BATCH_ARGS)

enhancer-review: enhancer-install ## [STEP 3] Review promoted rooms with vLLM into reviews.yaml (room=, force=1)
	cd $(ENHANCER_DIR) && ./run_batch.sh review $(ARGS) $(FORCE_ARG)

enhancer-verify: enhancer-install ## [STEP 4] Audit data/rooms-ai against the manifest, the 4x rule and the attempts (room=)
	cd $(ENHANCER_DIR) && ./run_batch.sh verify $(ARGS)

enhancer-check: enhancer-install ## Byte-compile the enhancer's Python modules
	$(ENHANCER_RUN) -m py_compile *.py && echo "check ok"

enhancer-test: enhancer-install ## Run the enhancer unit tests (no GPU, no network)
	$(ENHANCER_RUN) -m unittest discover -s . -p 'test_*.py'

enhancer-clean: ## Remove enhancer __pycache__ (never touches data/)
	cd $(ENHANCER_DIR) && find . -path ./$(VENV_DIR) -prune -o -type d -name "__pycache__" -exec rm -rf {} +

# ── Importer · HD backgrounds in the GOG app ─────────────────────────────────

importer-install: ## Initialize importer/.venv and install Pillow
	@cd $(IMPORTER_DIR) && if [ ! -d "$(VENV_DIR)" ]; then \
		python3 -m venv $(VENV_DIR); \
		$(PIP) install -U pip; \
		$(PIP) install -U pillow; \
	fi; \
	echo "importer environment setup complete."

importer-clean: ## Remove importer .venv, build/ and caches (keeps vendor/)
	cd $(IMPORTER_DIR) && rm -rf $(VENV_DIR) build && \
		find . -path ./vendor -prune -o -type d -name "__pycache__" -exec rm -rf {} +
	@echo "importer cleanup complete."

importer-engine-build: ## [STEP 1] Build the patched ScummVM into vendor/scummvm/ScummVM.app
	cd $(IMPORTER_DIR) && ./scripts/build_scummvm.sh

importer-engine-patch: ## Save edits to existing ScummVM files in vendor/scummvm to patches/scumm-hd.patch
	cd $(IMPORTER_DIR) && git -C vendor/scummvm diff > patches/scumm-hd.patch

importer-hd-validate: importer-install ## [STEP 2] Check every AI background against the game's rooms
	$(IMPORTER_RUN) -m importer validate $(PATHS)

importer-hd-install: importer-install ## [STEP 3] Install the patched ScummVM and the HD backgrounds (quit the game first)
	$(IMPORTER_RUN) -m importer install $(PATHS)

importer-hd-verify: importer-install ## [STEP 4] Check the installed engine and HD files
	$(IMPORTER_RUN) -m importer verify $(PATHS)

importer-hd-uninstall: importer-install ## Restore the app's original ScummVM and configfile
	$(IMPORTER_RUN) -m importer uninstall $(PATHS)

importer-test: importer-install ## Run the importer Python unit test suite
	$(IMPORTER_RUN) -m unittest discover -s tests

importer-test-engine: ## Build and run the compositor core's standalone tests
	cd $(IMPORTER_DIR) && mkdir -p build && $(CXX) -std=c++17 -Wall -Wextra -Werror \
		-DHD_COMPOSE_STANDALONE -Iengine engine/scumm/hd_compose.cpp engine/test_hd_compose.cpp \
		-o build/test_hd_compose && ./build/test_hd_compose

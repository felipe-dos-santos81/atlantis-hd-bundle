# Makefile for the Atlantis background regeneration kit
# Pipeline: caption -> (edit rooms.yaml) -> batch -> review -> batch ... -> verify
SERVICE = Atlantis Background Regen

VENV_DIR = .venv
PY = $(VENV_DIR)/bin/python

# Arguments, e.g. make batch room="1 58" workflow=qwen-image-2.1-i2i force=1
room ?=
src ?=
dst ?=
force ?=
memcheck ?= 1
strength ?=
workflow ?=
ARGS = $(foreach r,$(room),--room $(r)) $(if $(src),--src "$(src)") $(if $(dst),--dst "$(dst)")
BATCH_ARGS = $(if $(filter 0,$(memcheck)),--no-memory-check) $(if $(strength),--match-strength $(strength)) \
             $(if $(workflow),--workflow $(workflow)) $(if $(force),--force)

.PHONY: help install server caption dry-run batch review verify check test clean

help: ## Print this help message
	@printf '\033[01;32m${SERVICE}\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

# ── Environment ──────────────────────────────────────────────────────────────

install: ## Create .venv with Pillow, PyYAML and numpy (re-running is safe)
	@if [ ! -x "$(PY)" ]; then python3 -m venv $(VENV_DIR); fi
	@$(PY) -c 'import PIL, yaml, numpy' 2>/dev/null || $(VENV_DIR)/bin/pip install -q "pillow>=10" "pyyaml>=6" "numpy>=1.26"

server: ## Start ComfyUI on :8188 from ~/ComfyUI (override COMFY_DIR)
	./run_server.sh

clean: ## Remove __pycache__ (never touches data/)
	find . -path ./.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} +

# ── Pipeline ─────────────────────────────────────────────────────────────────

caption: install ## [STEP 1] Caption scene and insert rooms with vLLM into rooms.yaml (room=, force=1)
	./run_batch.sh caption $(ARGS) $(if $(force),--force)

dry-run: install ## [STEP 2a] Show what batch would render, without touching ComfyUI (room=, workflow=, strength=, force=1)
	./run_batch.sh batch --dry-run $(ARGS) $(BATCH_ARGS)

batch: install ## [STEP 2] Render rooms through ComfyUI into data/rooms-ai; stop vLLM first (room=, workflow=, strength=, memcheck=0, force=1)
	./run_batch.sh batch $(ARGS) $(BATCH_ARGS)

review: install ## [STEP 3] Review promoted rooms with vLLM into reviews.yaml (room=, force=1)
	./run_batch.sh review $(ARGS) $(if $(force),--force)

verify: install ## [STEP 4] Audit data/rooms-ai against the manifest, the 4x rule and the attempt records (room=)
	./run_batch.sh verify $(ARGS)

# ── Development ──────────────────────────────────────────────────────────────

check: install ## Byte-compile the Python modules
	@$(PY) -m py_compile *.py && echo "check ok"

test: install ## Run the unit tests (no GPU, no network)
	$(PY) -m unittest discover -s . -p 'test_*.py'

PYTHON ?= python3
PYTHON_BIN ?= .venv/bin/python
export PYTHONPATH := $(CURDIR)
PROGRAMS_ROOT ?= programs
WEBSITE_DIR ?= dag-gallery
CLOBBER ?= 0
VSCODE ?= .cursor
EDITOR_EXTENSIONS_DIR ?= $(HOME)/$(VSCODE)/extensions
.DEFAULT_GOAL := test

.PHONY: help setup evolve test test-compiler test-ssa test-ssa-highlighting score eval format json2ssa ssa2json generate-website setup-cursor

help: ## List available commands
	@printf 'Usage: make <command> [VARIABLE=value ...]\n\nCommands:\n'
	@awk 'BEGIN { FS = ":.*## " } /^[a-zA-Z0-9_-]+:.*## / { printf "  %-24s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf '\nOptions:\n  PYTHON_BIN=python3        Python executable\n  PROGRAMS_ROOT=programs   Program directory\n  WEBSITE_DIR=dag-gallery  Generated website directory\n  CLOBBER=1                Overwrite generated SSA files or website output\n  VSCODE=.vscode           Install highlighting for VS Code (default: .cursor)\n'

json2ssa: ## Convert JSON to SSA: INPUT=all|path.json [OUTPUT=path.ssa] [CLOBBER=1]
	@test -n "$(INPUT)" || { printf '%s\n' 'Usage: make json2ssa INPUT=all|path.json [OUTPUT=path.ssa] [CLOBBER=1]' >&2; exit 1; }
	@PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m program.representations.ssa json2ssa "$(INPUT)" --programs-root "$(PROGRAMS_ROOT)" $(if $(filter 1,$(CLOBBER)),--clobber) $(if $(OUTPUT),-o "$(OUTPUT)")

ssa2json: ## Convert SSA to JSON: INPUT=path.ssa [OUTPUT=path.json]
	@test -n "$(INPUT)" || { printf '%s\n' 'Usage: make ssa2json INPUT=path.ssa [OUTPUT=path.json]' >&2; exit 1; }
	@PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m program.representations.ssa ssa2json "$(INPUT)" $(if $(OUTPUT),-o "$(OUTPUT)")

generate-website: ## Generate the program gallery website
	PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m program.visualizations.gallery gallery --programs-dir "$(PROGRAMS_ROOT)/json" -o "$(WEBSITE_DIR)" $(if $(filter 1,$(CLOBBER)),--clobber)

setup-cursor: ## Install the SSA syntax-highlighting extension in Cursor
	@if [ -e "$(EDITOR_EXTENSIONS_DIR)/local.luminal-ssa-0.1.0" ] && [ ! -L "$(EDITOR_EXTENSIONS_DIR)/local.luminal-ssa-0.1.0" ]; then \
		printf '%s\n' 'Extension destination exists and is not a symlink; move it before installing.' >&2; exit 1; \
	fi
	@mkdir -p "$(EDITOR_EXTENSIONS_DIR)"
	ln -sfn "$(CURDIR)/program/visualizations/vscode" "$(EDITOR_EXTENSIONS_DIR)/local.luminal-ssa-0.1.0"
	@printf '%s\n' 'Run Developer: Reload Window in your editor to enable Luminal SSA highlighting.'

test: test-compiler test-ssa ## Run compiler and SSA tests (default)

test-ssa: ## Run SSA codec, round-trip, evaluation-format, and regeneration tests
	PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m unittest tests.program.representations.test_ssa_codec tests.program.representations.test_round_trip tests.test_evaluate_formats tests.test_regenerate_ssa -v

test-ssa-highlighting: ## Install test dependencies and run SSA syntax-highlighting tests
	npm ci --include=dev --prefix program/visualizations/vscode
	npm test --prefix program/visualizations/vscode

setup: ## Create or reuse .venv and install repository requirements
	$(PYTHON) -B scripts/setup.py

evolve: ## Run OpenEvolve autoresearch [ARGS=--check]
	$(PYTHON_BIN) -B autoresearch-openevolve/run.py $(ARGS)

test-compiler: ## Run compiler correctness tests
	$(PYTHON_BIN) -B evaluate.py test

score: ## Score compiler performance
	$(PYTHON_BIN) -B evaluate.py score

eval: ## Run compiler evaluation
	$(PYTHON_BIN) -B evaluate.py eval

format: ## Fix lint issues and format Python code with Ruff
	$(PYTHON_BIN) -m ruff check --fix .
	$(PYTHON_BIN) -m ruff format .

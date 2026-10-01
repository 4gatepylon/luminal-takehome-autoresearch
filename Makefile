PYTHON ?= python3
PYTHON_BIN ?= $(PYTHON)
PROGRAMS_ROOT ?= programs
WEBSITE_DIR ?= dag-gallery
CLOBBER ?= 0
VSCODE ?= .cursor
EDITOR_EXTENSIONS_DIR ?= $(HOME)/$(VSCODE)/extensions
.DEFAULT_GOAL := test

.PHONY: test test-compiler test-ssa test-ssa-highlighting score eval format json2ssa ssa2json generate-website setup-cursor

json2ssa:
	@test -n "$(INPUT)" || { printf '%s\n' 'Usage: make json2ssa INPUT=all|path.json [OUTPUT=path.ssa] [CLOBBER=1]' >&2; exit 1; }
	@PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m program.representations.ssa json2ssa "$(INPUT)" --programs-root "$(PROGRAMS_ROOT)" $(if $(filter 1,$(CLOBBER)),--clobber) $(if $(OUTPUT),-o "$(OUTPUT)")

ssa2json:
	@test -n "$(INPUT)" || { printf '%s\n' 'Usage: make ssa2json INPUT=path.ssa [OUTPUT=path.json]' >&2; exit 1; }
	@PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m program.representations.ssa ssa2json "$(INPUT)" $(if $(OUTPUT),-o "$(OUTPUT)")

generate-website:
	PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m program.visualizations.gallery gallery --programs-dir "$(PROGRAMS_ROOT)/json" -o "$(WEBSITE_DIR)" $(if $(filter 1,$(CLOBBER)),--clobber)

setup-cursor:
	@if [ -e "$(EDITOR_EXTENSIONS_DIR)/local.luminal-ssa-0.1.0" ] && [ ! -L "$(EDITOR_EXTENSIONS_DIR)/local.luminal-ssa-0.1.0" ]; then \
		printf '%s\n' 'Extension destination exists and is not a symlink; move it before installing.' >&2; exit 1; \
	fi
	@mkdir -p "$(EDITOR_EXTENSIONS_DIR)"
	ln -sfn "$(CURDIR)/program/visualizations/vscode" "$(EDITOR_EXTENSIONS_DIR)/local.luminal-ssa-0.1.0"
	@printf '%s\n' 'Run Developer: Reload Window in your editor to enable Luminal SSA highlighting.'

test: test-compiler test-ssa

test-ssa:
	PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m unittest tests.program.representations.test_ssa_codec tests.program.representations.test_round_trip tests.test_evaluate_formats tests.test_regenerate_ssa -v

test-ssa-highlighting:
	npm test --prefix program/visualizations/vscode

test-compiler:
	$(PYTHON_BIN) -B evaluate.py test

score:
	$(PYTHON_BIN) -B evaluate.py score

eval:
	$(PYTHON_BIN) -B evaluate.py eval

format:
	ruff check --fix .
	ruff format .

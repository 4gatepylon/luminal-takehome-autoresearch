PYTHON ?= python3
VENV ?= .venv
PYTHON_BIN := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff

.PHONY: help install format check test test-autoresearch test-compiler test-sandbox

help:
	@printf '%s\n' 'make install          Install the package and development tools (Python 3.10+)' \
	  'make format           Ruff format and fixes; original compiler/evaluator/tests excluded' \
	  'make check            Check formatting and lint without changing files' \
	  'make test             Infrastructure and original compiler tests; no model calls' \
	  'make test-sandbox     Opt-in real Codex OS sandbox probes; no model calls'

$(PYTHON_BIN):
	$(PYTHON) -m venv $(VENV)

install: $(PYTHON_BIN)
	$(PYTHON_BIN) -m pip install -e '.[dev]'

format:
	$(RUFF) format .
	$(RUFF) check --fix .

check:
	$(RUFF) format --check .
	$(RUFF) check .

test: test-autoresearch test-compiler

test-autoresearch:
	$(PYTHON_BIN) -B -m unittest discover -s tests/autoresearch -t . -v

test-compiler:
	$(PYTHON_BIN) -B -m unittest -v tests.test_machine tests.test_public_programs

test-sandbox:
	AUTORESEARCH_SANDBOX_TESTS=1 $(PYTHON_BIN) -B -m unittest -v tests.autoresearch.test_sandbox

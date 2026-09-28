PYTHON ?= python3
PYTHON_BIN ?= .venv/bin/python
export PYTHONPATH := $(CURDIR)

.PHONY: setup evolve test test-compiler score eval format

test: test-compiler

setup:
	bash scripts/setup.sh "$(PYTHON)"

evolve:
	$(PYTHON_BIN) -B autoresearch-openevolve/run.py $(ARGS)

test-compiler:
	$(PYTHON_BIN) -B evaluate.py test

score:
	$(PYTHON_BIN) -B evaluate.py score

eval:
	$(PYTHON_BIN) -B evaluate.py eval

format:
	$(PYTHON_BIN) -m ruff check --fix .
	$(PYTHON_BIN) -m ruff format .

PYTHON ?= python3
PYTHON_BIN ?= $(PYTHON)

.PHONY: test test-compiler score eval format

test: test-compiler

test-compiler:
	$(PYTHON_BIN) -B evaluate.py test

score:
	$(PYTHON_BIN) -B evaluate.py score

eval:
	$(PYTHON_BIN) -B evaluate.py eval

format:
	ruff check --fix .
	ruff format .

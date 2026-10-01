PYTHON ?= python3
PYTHON_BIN ?= $(PYTHON)

.PHONY: test test-compiler test-ssa test-ssa-highlighting score eval format

test: test-compiler test-ssa

test-ssa:
	PYTHONPATH="$(CURDIR)" $(PYTHON_BIN) -B -m unittest tests.program.representations.test_ssa_codec tests.test_evaluate_formats -v

test-ssa-highlighting:
	npm test --prefix vscode/ssa

test-compiler:
	$(PYTHON_BIN) -B evaluate.py test

score:
	$(PYTHON_BIN) -B evaluate.py score

eval:
	$(PYTHON_BIN) -B evaluate.py eval

format:
	ruff check --fix .
	ruff format .

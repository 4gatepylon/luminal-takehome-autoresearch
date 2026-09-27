PYTHON ?= python3
PYTHON_BIN ?= $(PYTHON)

.PHONY: test test-compiler score eval

test: test-compiler

test-compiler:
	$(PYTHON_BIN) -B -m unittest -v tests.test_machine tests.test_public_programs

score:
	$(PYTHON_BIN) -B score.py

eval: test
	$(MAKE) score

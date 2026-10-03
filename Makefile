.PHONY: test score help

test:
	python3 -m unittest -v

score:
	python3 score.py

help:
	@printf '%s\n' 'Available commands:' \
	  '  make test   Run unit tests' \
	  '  make score  Run scoring' \
	  '  make help   Show this help'

# Python conventions

- All compiler and AI-written candidate code must execute inside `run_in_sandbox`.
  Trusted runners, tests, and grading code may execute in the parent process.
- Always invoke scripts from the repository root with the repository root on
  `PYTHONPATH`. Use ordinary imports; do not add import-path discovery or fallback
  layouts.
- Always put every import at the top of its module, after the module docstring.
  Do not use function-local imports.

# OpenEvolve autoresearch

Run from the repository root with Python 3.10+ on macOS:

```sh
export PYTHONPATH="$PWD"
python -B autoresearch-openevolve/run.py  # -B: no bytecode caches
```

# Python conventions

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

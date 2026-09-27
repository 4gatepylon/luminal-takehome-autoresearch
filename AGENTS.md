# Python conventions

- Always invoke scripts from the repository root with the repository root on
  `PYTHONPATH`. Use ordinary imports; do not add import-path discovery or fallback
  layouts.
- Always put every import at the top of its module, after the module docstring.
  Do not use function-local imports.
- Always use `work/compiler.py` as the compiler being evolved. Do not fall back
  to the root `compiler.py`. The trusted `machine.py`, `programs/`, and `README.md`
  are at the repository root.

# OpenEvolve autoresearch

Run from the repository root with Python 3.10+ on macOS:

```sh
export PYTHONPATH="$PWD"
python -B autoresearch-openevolve/run.py
```

Use `--check` to evaluate `work/compiler.py` without API calls. Keep all run
artifacts under `.autoresearch-openevolve/`; `-B` disables bytecode files outside
that directory. Keep generated compiler execution inside `run_in_sandbox` and
grade its JSON output with the trusted machine implementation in the parent
process.

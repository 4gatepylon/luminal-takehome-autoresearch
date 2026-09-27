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
python -B autoresearch-openevolve/run.py  # -B: no bytecode caches
```

Use `--check` to evaluate `work/compiler.py` without API calls. Keep all run
artifacts under `.autoresearch-openevolve/`. Run the shared
`evaluate.eval(compiler_filepath=...)` API inside `run_in_sandbox` so candidate
loading, public tests, and scoring are sandboxed. The parent collects JSON
metrics or reports evaluation errors.

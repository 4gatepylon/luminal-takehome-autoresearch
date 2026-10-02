# Terminology

- Never introduce new terminology. Use only terms already used in the repository
  or explicitly supplied by the user, including in code, test names,
  documentation, and explanations.

# Simplicity

Implement every feature with the smallest scope and simplest code possible,
making it easy to read, debug, and extend without compiler-level performance
optimizations or unrequested "better" versions.
Keep PRs small and reviewable, ideally 10–100 changed lines, unless the user
explicitly requests otherwise.
If a task cannot be completed within these constraints, stop and ask the user
how to proceed.

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

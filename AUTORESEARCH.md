# Compiler autoresearch

A small Python loop: ask Codex to improve `compiler.py`, run the existing tests
and benchmark, record the result in DuckDB, and start the next attempt from the
best compiler so far. By default, each run starts from `main`.

## Run

Use Python 3.10+ on macOS or Linux, Git, and an authenticated Codex CLI:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install -g @openai/codex  # skip if codex is already installed
codex login
.venv/bin/python autoresearch.py --iterations 10
```

Python invokes the installed CLI directly; no Python Codex SDK is needed.
The default model is `gpt-6-astra` with `xhigh` reasoning. Override with `--model`
and `--effort`. `--codex-timeout` defaults to 900 seconds per attempt and
`--eval-timeout` to 180 seconds per evaluation command. Use `--iterations 0` to
check the baseline and database without making a model call.

Each invocation evaluates `--base main` first, then creates branches named
`autoresearch/<run-id>/<iteration>` in temporary worktrees. Your current checkout
is untouched. Each compiler proposal is committed, including failed or slower
ones; only a correct, strictly better combined score becomes the next parent.
Comparisons use the benchmark's printed precision (three decimal places).
Every generated commit includes `Implemented by codex astra 6 xhigh.`

Codex uses [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
with `workspace-write` and approval policy `never`, allowing local edits and evals
without prompts. `--no-daemon` keeps each attempt in its own process group so
timeouts can stop it. The prompt restricts edits to `compiler.py`; the runner rejects
other tracked changes, untracked source files, and agent-made commits or branch
switches before evaluation. This is a checked edit policy, not a per-file OS
sandbox: Codex can write within its disposable worktree. The supplied evaluator
and tests are never intentionally modified. Temporary worktrees are removed;
proposal branches, logs, and database records remain.

## Results and continuing a run

The single `results` table in `.autoresearch/results.duckdb` contains run/iteration,
timestamp, branch, parent and proposal commits, status, cycle speedup, scratch
reduction, combined score, duration, model/effort, log directory, and error.
Iteration 0 is the baseline. Status is `baseline`, `improved`, `rejected`,
`no_change`, `failed`, `timeout`, or `interrupted`; an abruptly killed runner may
leave a `running` row. Logs beside the DB contain prompts, Codex output, and eval
output. Only one runner should write a given DB at a time.

```sh
.venv/bin/python - <<'PY'
import duckdb
with duckdb.connect('.autoresearch/results.duckdb', read_only=True) as db:
    print(db.sql('''SELECT branch, commit_sha, status, combined_score
                   FROM results ORDER BY started_at, iteration'''))
PY

# Continue from a winning branch printed by the runner:
.venv/bin/python autoresearch.py --base autoresearch/<run-id>/<iteration> --iterations 10
```

`--db PATH` chooses another database. No branch is merged or pushed automatically.
Ctrl-C kills the current subprocess group, records the interrupted attempt, and
cleans up its worktree.

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
.venv/bin/python -m autoresearch --iterations 10
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

## Permissions

Every attempt receives the contents of `autoresearch/agent_instructions.md` from the runner's
checkout, even when its starting commit does not contain that file. The runner
also configures a [Codex permission profile](https://learn.chatgpt.com/docs/permissions)
that extends `:read-only` and grants write access to the absolute path of just
that attempt's `compiler.py`:

| Capability | Research agent |
| --- | --- |
| Read repository and local files | Allowed, subject to OS and managed policy |
| Modify `compiler.py` in the attempt's worktree | Allowed |
| Modify `programs/`, `tests/`, `machine.py`, `score.py`, or other files | Blocked by the filesystem sandbox |
| Create files, including temporary files and bytecode caches | Blocked |
| Change Git metadata, logs, or the results database | Blocked |
| Run existing tests and benchmark | Allowed; use Python `-B` |
| Network access from shell commands | Blocked |
| Request broader permissions | Disabled (`approval_policy=never`) |

The runner performs its own tests and scoring under `codex sandbox` with the
`:read-only` profile, so even proposed compiler code cannot write files during
evaluation. The parent Python runner retains permission to create worktrees,
commit compiler changes, and write DuckDB records and logs. Codex's own model
and authentication traffic is separate from sandboxed command network access.

Use a current Codex CLI with permission-profile support (tested with 0.157.0).
The CLI starts with `--ignore-user-config` to avoid inheriting legacy
`sandbox_mode` settings that override permission profiles; saved authentication
still loads. Managed requirements remain in effect. System/project configuration
must also avoid mixing legacy sandbox settings with permission profiles.
`--strict-config` rejects unknown settings; there is no workspace-write fallback.
`--no-daemon` keeps each attempt in its own process group so timeouts can stop it.

The Git checks remain as a second check before accepting a proposal. Temporary
worktrees are removed; proposal branches, logs, and database records remain.

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
.venv/bin/python -m autoresearch --base autoresearch/<run-id>/<iteration> --iterations 10
```

`--db PATH` chooses another database. No branch is merged or pushed automatically.
Ctrl-C kills the current subprocess group, records the interrupted attempt, and
cleans up its worktree.

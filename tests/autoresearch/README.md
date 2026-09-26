# Test boundaries

Run from the repository root with the project's dependencies installed:

```sh
python -B -m unittest discover -s tests/autoresearch -t . -v
```

| Test module | Real behavior exercised | Replaced or excluded |
| --- | --- | --- |
| `test_config.py` | YAML defaults/overrides, validation, round-trip, unsafe-tag rejection | No Git, DB, or model |
| `test_cli.py` | Click options, help/config output, validation and missing-Codex errors | Git discovery and runner mocked |
| `test_database.py` | SQLAlchemy + temporary DuckDB, durable lifecycle writes, duplicates, history, original schema | No agent; no remote databases |
| `test_environment.py` | Temporary Git repos/worktrees, partial-creation cleanup, preservation of primary errors, hook bypass without changing manual Git, commit/scope checks, child cleanup on every exit, structured scoring returns using worktree inputs and noisy diagnostics | Git failure points and interruption injected; Codex sandbox/agent execution and correctness-test execution mocked for scoring integration |
| `test_score.py` | Importable scoring API, silent return values, CLI presentation, empty input rejection | Public programs compiled with the serial reference compiler |
| `test_runner.py` | Real Git + DuckDB across baseline/improvement/rejection/no-change/failure/timeout/interruption; quota stops/errors; invalid commits retained without evaluation; creation/cleanup failures cannot promote proposals | Codex execution, quota responses, benchmark execution, commit mutation, and creation/cleanup failure scripted |
| `test_usage.py` | Named quota thresholds, multiple buckets, monthly credit limits, missing/unsupported data; real Codex Python SDK handshake, timeout, response validation, process cleanup | Local scripted app server; no credentials, network, or model |
| `test_sandbox.py` | Actual Codex OS sandbox: `work/`-only writes, read-only evaluation, blocked loopback networking | Opt-in; no model call |

The original `tests/test_machine.py` and `tests/test_public_programs.py` are
unchanged and test the simulator contract and eight public compiler programs:

```sh
python -B -m unittest -v tests.test_machine tests.test_public_programs
python -B score.py
```

Those two modules and the `score.score()` library function are the runner's complete
evaluation set. New infrastructure tests never influence experiment scores.

OS sandbox probes require a compatible Codex CLI, permissions to launch its
platform sandbox, and managed policy that permits the tested profiles:

```sh
AUTORESEARCH_SANDBOX_TESTS=1 python -B -m unittest -v tests.autoresearch.test_sandbox
```

The ordinary suite skips these probes explicitly. Once enabled, sandbox startup
or enforcement failures fail the tests. A real baseline smoke test (no model
call) also exercises worktrees, the installed sandbox, supplied tests/scoring,
and persistence together:

```sh
python -B -m autoresearch --iterations 0 --db /tmp/autoresearch-smoke.duckdb
```

Not covered: live model quality/authentication, arbitrary malicious compiler
behavior, secret isolation, cross-platform sandbox equivalence, hidden compiler
programs, remote databases, concurrent writers, distributed scheduling, schema
migrations, and recovery after a machine crash. Scope checks and successful
public tests are not a security proof.

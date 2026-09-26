#!/usr/bin/env python3
"""Propose compiler-only changes with Codex, evaluate them, and log to DuckDB."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

import duckdb


ATTRIBUTION = "Implemented by codex astra 6 xhigh."
METRICS = {
    "cycle_speedup": "public geometric-mean speedup",
    "scratch_reduction": "public geometric-mean scratch reduction",
    "combined_score": "public combined score",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    run_id VARCHAR, iteration INTEGER, started_at TIMESTAMPTZ DEFAULT current_timestamp,
    branch VARCHAR, parent_commit VARCHAR, commit_sha VARCHAR, status VARCHAR,
    cycle_speedup DOUBLE, scratch_reduction DOUBLE, combined_score DOUBLE,
    elapsed_seconds DOUBLE, model VARCHAR, effort VARCHAR, logs VARCHAR, error VARCHAR,
    PRIMARY KEY (run_id, iteration)
)
"""


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=True,
    )
    return result.stdout.strip()


@contextmanager
def worktree(repo: Path, commit: str, branch: str | None = None):
    """Only the disposable checkout is ever edited or forcibly cleaned up."""
    with tempfile.TemporaryDirectory(prefix="luminal-autoresearch-") as directory:
        path = Path(directory) / "work"
        options = ["-b", branch] if branch else ["--detach"]
        git(repo, "worktree", "add", *options, str(path), commit)
        try:
            yield path
        finally:
            git(repo, "worktree", "remove", "--force", str(path))


def execute(command: list[str], cwd: Path, log: Path, timeout: float,
            prompt: str | None = None) -> None:
    """Bound each command and kill its children too on timeout or Ctrl-C."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with log.open("a") as output:
        with subprocess.Popen(
            command, cwd=cwd, env=env, text=True, stdin=subprocess.PIPE,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
        ) as process:
            try:
                process.communicate(prompt, timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
            if process.returncode:
                raise RuntimeError(f"{command[0]} exited {process.returncode}; see {log}")


def evaluate(path: Path, log: Path, timeout: float) -> dict[str, float]:
    # The proposed compiler executes here too. Keep the evaluator's filesystem
    # read-only; the parent runner, outside the sandbox, owns logs and Git writes.
    sandbox = ["codex", "sandbox", "--include-managed-config",
               "--permission-profile", ":read-only", "--cd", str(path), "--"]
    execute([*sandbox, sys.executable, "-B", "-m", "unittest", "-v"], path, log, timeout)
    execute([*sandbox, sys.executable, "-B", "score.py"], path, log, timeout)
    output = log.read_text()
    metrics = {}
    for name, label in METRICS.items():
        match = re.search(rf"^{re.escape(label)}: ([0-9]+\.[0-9]+)x$", output, re.M)
        if not match or float(match[1]) <= 0:
            raise RuntimeError(f"Missing or invalid {name}; see {log}")
        metrics[name] = float(match[1])
    return metrics


def check_scope(path: Path, parent: str, branch: str) -> bool:
    """Reject Git mutations, extra files, and changes outside compiler.py."""
    if git(path, "rev-parse", "HEAD") != parent:
        raise RuntimeError("Codex changed HEAD; only the runner may commit")
    if git(path, "branch", "--show-current") != branch:
        raise RuntimeError("Codex switched branches")
    # Check the index separately: a staged edit can be hidden by restoring only
    # the working copy, and would otherwise sneak into the runner's commit.
    changed = set(git(path, "diff", "--name-only").splitlines())
    changed.update(git(path, "diff", "--cached", "--name-only").splitlines())
    untracked = git(path, "ls-files", "--others", "--exclude-standard")
    if changed - {"compiler.py"} or untracked:
        raise RuntimeError(f"Changes outside compiler.py: {sorted(changed)} {untracked}")
    compiler = path / "compiler.py"
    if compiler.is_symlink() or not compiler.is_file():
        raise RuntimeError("compiler.py must remain a regular file")
    return bool(changed)


def compiler_permission_args(path: Path) -> list[str]:
    """Allow reads, but grant writes only to this checkout's compiler.py."""
    compiler = json.dumps(str(path.resolve() / "compiler.py"))
    policy = ('{extends=":read-only", filesystem={' + compiler + '="write"}, '
              'network={enabled=false}}')
    return ["-c", 'default_permissions="luminal_compiler"',
            "-c", f"permissions.luminal_compiler={policy}"]


def codex_command(path: Path, model: str, effort: str) -> list[str]:
    return [
        "codex", "--no-daemon", "--ask-for-approval", "never", "exec",
        # Legacy sandbox settings override permission profiles. Ignore personal
        # config instead of inheriting workspace-write; saved auth still loads.
        "--ignore-user-config", "--strict-config", "--ephemeral", "--color", "never",
        *compiler_permission_args(path),
        "--model", model, "-c", f'model_reasoning_effort="{effort}"',
        "--cd", str(path), "-",
    ]


def research(args: argparse.Namespace, repo: Path) -> None:
    base = git(repo, "rev-parse", f"{args.base}^{{commit}}")
    # Read the runner's rules even when the experiment starts from an older
    # commit (such as main) that does not contain agent_instructions.md.
    rules = Path(__file__).with_name("agent_instructions.md").read_text()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    db_path = args.db.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logs_root = db_path.parent / "logs" / run_id
    best_commit, best_branch, best_score = base, args.base, 0.0
    with duckdb.connect(str(db_path)) as db:
        db.execute(SCHEMA)
        # Iteration zero evaluates the actual starting commit without using Codex.
        for iteration in range(args.iterations + 1):
            branch = f"autoresearch/{run_id}/{iteration:04d}" if iteration else args.base
            parent = best_commit
            logs = logs_root / f"{iteration:04d}"
            logs.mkdir(parents=True)
            db.execute(
                """INSERT INTO results
                   (run_id, iteration, branch, parent_commit, status, model, effort, logs)
                   VALUES (?, ?, ?, ?, 'running', ?, ?, ?)""",
                [run_id, iteration, branch, parent, args.model, args.effort, str(logs)],
            )
            start = time.monotonic()
            status, error, commit, metrics = "failed", None, None, {}
            print(f"[{iteration}/{args.iterations}] {branch}", flush=True)
            try:
                with worktree(repo, parent, branch if iteration else None) as path:
                    if iteration:
                        recent = db.execute(
                            """SELECT iteration, status, combined_score, error FROM results
                               WHERE run_id = ? AND iteration < ?
                               ORDER BY iteration DESC LIMIT 5""", [run_id, iteration],
                        ).fetchall()
                        prompt = f"""Follow these instructions from agent_instructions.md:
{rules}

Improve this repository's compiler performance.
Read README.md, compiler.py, machine.py, and the supplied tests and programs.
Make one focused, general improvement to scheduling or scratch allocation.
Edit ONLY compiler.py. Do not create or modify any other files, including tests,
benchmarks, programs, machine.py, documentation, or Git configuration/history.
Do not commit or switch branches; the runner handles Git. Use only the standard
library. Do not hardcode public programs or alter evaluation behavior.
The filesystem is read-only except for compiler.py. Edit that file in place;
do not create temporary files or bytecode caches. Run inline checks with -B.
Run {sys.executable} -B -m unittest -v and {sys.executable} -B score.py.
Maximize the public combined score while preserving correctness for arbitrary
valid inputs. The score equally weights cycle speedup and scratch reduction.
The current best combined score is {best_score:.3f}x. Try a new idea informed by
these recent attempts (iteration, status, score, error): {recent!r}
You have at most {args.codex_timeout:g} seconds. Finish with a short explanation
of your hypothesis, change, and measured result. Only compiler.py may change.
"""
                        (logs / "prompt.txt").write_text(prompt)
                        execute(codex_command(path, args.model, args.effort), path,
                                logs / "codex.log", args.codex_timeout, prompt)
                        if not check_scope(path, parent, branch):
                            status = "no_change"
                            continue
                        # Keep even incorrect/non-improving compiler proposals so
                        # every evaluated change can be reproduced from its branch.
                        git(path, "add", "--", "compiler.py")
                        message = f"Autoresearch compiler attempt {run_id}/{iteration}\n\n{ATTRIBUTION}\n"
                        message_path = logs / "commit-message.txt"
                        message_path.write_text(message)
                        git(path, "commit", "--file", str(message_path))
                    commit = git(path, "rev-parse", "HEAD")
                    metrics = evaluate(path, logs / "eval.log", args.eval_timeout)
                    # Evaluation must not leave source or test changes behind.
                    if check_scope(path, commit, branch if iteration else ""):
                        raise RuntimeError("Evaluation modified compiler.py")
                    if metrics["combined_score"] > best_score:
                        best_commit, best_branch, best_score = commit, branch, metrics["combined_score"]
                        status = "improved" if iteration else "baseline"
                    else:
                        status = "rejected"
            except KeyboardInterrupt:
                status, error = "interrupted", "Interrupted by user"
                raise
            except Exception as exc:
                error = str(exc)
                if isinstance(exc, subprocess.CalledProcessError):
                    error += "\n" + exc.stderr
                if isinstance(exc, subprocess.TimeoutExpired):
                    status = "timeout"
                if iteration == 0:
                    raise RuntimeError(f"Baseline evaluation failed: {error}") from exc
            finally:
                db.execute(
                    """UPDATE results SET commit_sha=?, status=?, cycle_speedup=?,
                       scratch_reduction=?, combined_score=?, elapsed_seconds=?, error=?
                       WHERE run_id=? AND iteration=?""",
                    [commit, status, metrics.get("cycle_speedup"), metrics.get("scratch_reduction"),
                     metrics.get("combined_score"), time.monotonic() - start, error, run_id, iteration],
                )
                print(f"  {status}: score={metrics.get('combined_score')} {error or ''}", flush=True)
        print(f"Best: {best_branch} ({best_commit}), score={best_score:.3f}x\nResults: {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10, help="Codex attempts; 0 evaluates the baseline only")
    parser.add_argument("--base", default="main", help="Starting branch or commit (use a previous winner to resume)")
    parser.add_argument("--db", type=Path, default=Path(".autoresearch/results.duckdb"))
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh"], default="xhigh")
    parser.add_argument("--codex-timeout", type=float, default=900, help="Seconds allowed per Codex attempt")
    parser.add_argument("--eval-timeout", type=float, default=180, help="Seconds allowed per evaluation command")
    args = parser.parse_args()
    if args.iterations < 0 or min(args.codex_timeout, args.eval_timeout) <= 0:
        parser.error("iterations must be nonnegative and timeouts must be positive")
    if not shutil.which("codex"):
        parser.error("Install the Codex CLI and run codex login first (see autoresearch/README.md)")
    repo = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    research(args, repo)


if __name__ == "__main__":
    main()

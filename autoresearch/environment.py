"""Implemented by Codex (GPT-6).

Host Git operations, sandboxed child commands, and artifact validation.

The parent runner is trusted. Only disposable worktrees are forcibly removed.
"""

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile


# These surfaces have separate controls from the local command sandbox.
DISABLED_AGENT_FEATURES = (
    "multi_agent",
    "multi_agent_v2",
    "apps",
    "plugins",
    "browser_use",
    "browser_use_external",
    "in_app_browser",
    "computer_use",
    "image_generation",
)


def git(repo: Path, *args: str) -> str:
    """Invoke Git without a shell; return stdout or raise with captured stderr."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


class GitRepository:
    """Git lifecycle operations for a trusted repository and disposable checkouts."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    @classmethod
    def discover(cls, start: Path) -> "GitRepository":
        return cls(Path(git(start, "rev-parse", "--show-toplevel")))

    def resolve(self, ref: str) -> str:
        return git(self.root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")

    @contextmanager
    def worktree(self, commit: str, branch: str | None = None):
        """Remove the checkout on success, failure, or interruption; retain branches."""
        with tempfile.TemporaryDirectory(prefix="luminal-autoresearch-") as directory:
            path = Path(directory) / "work"
            options = ["-b", branch] if branch else ["--detach"]
            git(self.root, "worktree", "add", *options, str(path), commit)
            try:
                yield path
            finally:
                git(self.root, "worktree", "remove", "--force", str(path))

    def commit_compiler(self, path: Path, run_id: str, iteration: int, *, model: str, effort: str) -> str:
        """Commit the already validated proposal, including its author attribution."""
        git(path, "add", "--", "compiler.py")
        message = f"Autoresearch compiler attempt {run_id}/{iteration}\n\nImplemented by Codex ({model}, reasoning effort: {effort}).\n"
        git(path, "commit", "-m", message)
        return git(path, "rev-parse", "HEAD")


METRICS = {
    "cycle_speedup": "public geometric-mean speedup",
    "scratch_reduction": "public geometric-mean scratch reduction",
    "combined_score": "public combined score",
}


def execute(command: list[str], cwd: Path, log: Path, timeout: float, prompt: str | None = None) -> None:
    """Bound each command and kill its children too on timeout or Ctrl-C."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with log.open("a") as output:
        with subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        ) as process:
            try:
                process.communicate(prompt, timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise
            if process.returncode:
                raise RuntimeError(f"{command[0]} exited {process.returncode}; see {log}")


def evaluate(path: Path, logs: Path, timeout: float) -> dict[str, float]:
    """Log tests and scoring separately; accept one finite positive value per metric."""
    # The proposed compiler executes here too. Keep the evaluator's filesystem
    # read-only; the parent runner, outside the sandbox, owns logs and Git writes.
    sandbox = ["codex", "sandbox", "--include-managed-config", "--permission-profile", ":read-only", "--cd", str(path), "--"]
    execute(
        [*sandbox, sys.executable, "-B", "-m", "unittest", "-v", "tests.test_machine", "tests.test_public_programs"],
        path,
        logs / "tests.log",
        timeout,
    )
    score_log = logs / "score.log"
    execute([*sandbox, sys.executable, "-B", "score.py"], path, score_log, timeout)
    output = score_log.read_text()
    metrics = {}
    for name, label in METRICS.items():
        matches = re.findall(rf"^{re.escape(label)}: ([0-9]+\.[0-9]+)x$", output, re.M)
        if len(matches) != 1 or not math.isfinite(value := float(matches[0])) or value <= 0:
            raise RuntimeError(f"Missing or invalid {name}; see {score_log}")
        metrics[name] = value
    return metrics


def validate_artifact(path: Path, parent: str, branch: str) -> bool:
    """Reject Git mutations, extra files, and changes outside compiler.py."""
    if git(path, "rev-parse", "HEAD") != parent:
        raise RuntimeError("Codex changed HEAD; only the runner may commit")
    if git(path, "branch", "--show-current") != branch:
        raise RuntimeError("Codex switched branches")
    # Check the index separately: a staged edit can be hidden by restoring only
    # the working copy, and would otherwise sneak into the runner's commit.
    changed = set(git(path, "diff", "--name-only").splitlines())
    changed.update(git(path, "diff", "--cached", "--name-only").splitlines())
    untracked = git(path, "ls-files", "--others")
    if changed - {"compiler.py"} or untracked:
        raise RuntimeError(f"Changes outside compiler.py: {sorted(changed)} {untracked}")
    compiler = path / "compiler.py"
    if compiler.is_symlink() or not compiler.is_file():
        raise RuntimeError("compiler.py must remain a regular file")
    return bool(changed)


def compiler_permission_args(path: Path) -> list[str]:
    """Allow reads, but grant writes only to this checkout's compiler.py."""
    compiler = json.dumps(str(path.resolve() / "compiler.py"))
    policy = '{extends=":read-only", filesystem={' + compiler + '="write"}, network={enabled=false}}'
    return ["-c", 'default_permissions="luminal_compiler"', "-c", f"permissions.luminal_compiler={policy}"]


def codex_command(path: Path, model: str, effort: str) -> list[str]:
    return [
        "codex",
        "--no-daemon",
        "--ask-for-approval",
        "never",
        "exec",
        # Legacy sandbox settings override permission profiles. Ignore personal
        # config instead of inheriting workspace-write; saved auth still loads.
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--ephemeral",
        "--color",
        "never",
        *compiler_permission_args(path),
        "-c",
        'web_search="disabled"',
        *[arg for feature in DISABLED_AGENT_FEATURES for arg in ("--disable", feature)],
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "--cd",
        str(path),
        "-",
    ]

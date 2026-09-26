"""Implemented by Codex (GPT-6).

Host Git operations, sandboxed child commands, and artifact validation.

The parent runner is trusted. Only disposable worktrees are forcibly removed.
"""

from contextlib import contextmanager
import json
import logging
import math
import os
from pathlib import Path
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


def git(repo: Path, *args: str, raw: bool = False) -> str:
    """Invoke Git without hooks or a shell; raw preserves whitespace in file lists."""
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout if raw else result.stdout.strip()


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
        """Clean up even partial creation; preserve primary errors and retain branches."""
        with tempfile.TemporaryDirectory(prefix="luminal-autoresearch-") as directory:
            path = (Path(directory) / "work").resolve()
            options = ["-b", branch] if branch else ["--detach"]
            failed = False
            try:
                git(self.root, "worktree", "add", *options, str(path), commit)
                yield path
            except BaseException:
                failed = True
                raise
            finally:
                try:
                    registrations = git(self.root, "worktree", "list", "--porcelain", "-z", raw=True).split("\0")
                    if f"worktree {path}" in registrations:
                        git(self.root, "worktree", "remove", "--force", str(path))
                except Exception:
                    if not failed:
                        raise
                    logging.getLogger(__name__).exception("Cleanup also failed for temporary worktree %s", path)

    def commit_compiler(self, path: Path, run_id: str, iteration: int, *, model: str, effort: str) -> str:
        """Commit the already validated proposal, including its author attribution."""
        git(path, "add", "--", "compiler.py")
        message = f"Autoresearch compiler attempt {run_id}/{iteration}\n\nImplemented by Codex ({model}, reasoning effort: {effort}).\n"
        git(path, "commit", "-m", message)
        return git(path, "rev-parse", "HEAD")


def execute(command: list[str], cwd: Path, log: Path, timeout: float, prompt: str | None = None, *, capture_result: bool = False) -> str | None:
    """Bound a command and stop its process group on every exit; optionally capture stdout."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with log.open("a") as output:
        with subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if capture_result else output,
            stderr=output,
            start_new_session=True,
        ) as process:
            try:
                result, _ = process.communicate(prompt, timeout=timeout)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            if process.returncode:
                raise RuntimeError(f"{command[0]} exited {process.returncode}; see {log}")
            return result


def evaluate(path: Path, logs: Path, timeout: float) -> dict[str, float]:
    """Invoke the scoring library in the sandbox; logs never supply metric values."""
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
    # Load the runner's scoring library, even when the worktree predates its API.
    # Its compiler/machine imports and explicit program directory use the worktree.
    # JSON transports the function's return value; all printed diagnostics go to stderr.
    scoring_script = """import contextlib, json, runpy, sys
from pathlib import Path
with contextlib.redirect_stdout(sys.stderr):
    score = runpy.run_path(sys.argv[1])["score"]
    metrics = score(program_dir=Path.cwd() / "programs")
json.dump(metrics, sys.stdout, allow_nan=False)
"""
    score_module = Path(__file__).resolve().parents[1] / "score.py"
    result = execute([*sandbox, sys.executable, "-B", "-c", scoring_script, str(score_module)], path, score_log, timeout, capture_result=True)
    metrics = json.loads(result)
    if not isinstance(metrics, dict):
        raise RuntimeError(f"Scoring function must return a metrics dictionary; see {score_log}")
    for name in ("cycle_speedup", "scratch_reduction", "combined_score"):
        value = metrics.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise RuntimeError(f"Missing or invalid {name}; see {score_log}")
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


def validate_proposal_commit(path: Path, parent: str, commit: str, branch: str) -> None:
    """Require one compiler-only commit from parent, on branch with a clean checkout."""
    if validate_artifact(path, commit, branch):
        raise RuntimeError("Proposal commit left uncommitted changes")
    parents = git(path, "rev-list", "--parents", "-n", "1", commit, "--").split()[1:]
    if parents != [parent]:
        raise RuntimeError("Proposal must be exactly one commit from the expected parent")
    changed = set(git(path, "diff", "--no-renames", "--name-only", "-z", parent, commit, "--", raw=True).split("\0")[:-1])
    if changed != {"compiler.py"}:
        raise RuntimeError(f"Proposal commit must change only compiler.py: {sorted(changed)}")


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

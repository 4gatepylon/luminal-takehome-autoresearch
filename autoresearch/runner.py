"""Implemented by Codex (GPT-6).

One synchronous runner: baseline, then one proposal and evaluation at a time."""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .config import ResearchConfig
from .database import ResultsStore
from .environment import GitRepository, codex_command, evaluate, execute, validate_artifact


def research(args: ResearchConfig, repo: Path) -> None:
    repository = GitRepository(repo)
    base = repository.resolve(args.base)
    # Read the runner's rules even when the experiment starts from an older
    # commit (such as main) that does not contain agent_instructions.md.
    rules = Path(__file__).with_name("agent_instructions.md").read_text()
    prompt_template = Path(__file__).with_name("agent_prompt.md").read_text()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    db_path = (repo / args.db).resolve()
    logs_root = db_path.parent / "logs" / run_id
    best_commit, best_branch, best_score = base, args.base, 0.0
    with ResultsStore(db_path) as store:
        # Iteration zero evaluates the actual starting commit without using Codex.
        for iteration in range(args.iterations + 1):
            branch = f"autoresearch/{run_id}/{iteration:04d}" if iteration else args.base
            parent = best_commit
            logs = logs_root / f"{iteration:04d}"
            logs.mkdir(parents=True)
            store.start_attempt(
                run_id,
                iteration,
                branch=branch,
                parent_commit=parent,
                model=args.model,
                effort=args.effort,
                logs=logs,
            )
            start = time.monotonic()
            status, error, commit, metrics = "failed", None, None, {}
            print(f"[{iteration}/{args.iterations}] {branch}", flush=True)
            try:
                with repository.worktree(parent, branch if iteration else None) as path:
                    if iteration:
                        recent = store.recent_attempts(run_id, iteration)
                        prompt = prompt_template.format(
                            rules=rules,
                            python=sys.executable,
                            best_score=best_score,
                            recent=recent,
                            codex_timeout=args.codex_timeout,
                        )
                        (logs / "prompt.txt").write_text(prompt)
                        execute(codex_command(path, args.model, args.effort), path, logs / "codex.log", args.codex_timeout, prompt)
                        if not validate_artifact(path, parent, branch):
                            status = "no_change"
                            continue
                        # Keep even incorrect/non-improving compiler proposals so
                        # every evaluated change can be reproduced from its branch.
                        commit = repository.commit_compiler(path, run_id, iteration, model=args.model, effort=args.effort)
                    else:
                        commit = parent
                    metrics = evaluate(path, logs, args.eval_timeout)
                    # Evaluation must not leave source or test changes behind.
                    if validate_artifact(path, commit, branch if iteration else ""):
                        raise RuntimeError("Evaluation modified compiler.py")
                # Select the next parent only after validation and worktree cleanup succeed.
                if metrics["combined_score"] > best_score:
                    best_commit, best_branch, best_score = commit, branch, metrics["combined_score"]
                    status = "improved" if iteration else "baseline"
                else:
                    status = "rejected"
            except KeyboardInterrupt:
                status, error = "interrupted", "Interrupted by user"
                raise
            except Exception as exc:
                status = "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "failed"
                error = str(exc)
                if isinstance(exc, subprocess.CalledProcessError):
                    error += "\n" + (exc.stderr or "")
                if iteration == 0:
                    raise RuntimeError(f"Baseline evaluation failed: {error}") from exc
            finally:
                store.finish_attempt(
                    run_id,
                    iteration,
                    commit_sha=commit,
                    status=status,
                    metrics=metrics,
                    elapsed_seconds=time.monotonic() - start,
                    error=error,
                )
                print(f"  {status}: score={metrics.get('combined_score')} {error or ''}", flush=True)
        print(f"Best: {best_branch} ({best_commit}), score={best_score:.3f}x\nResults: {db_path}")

"""Persistence boundary for the runner's single results database."""

from pathlib import Path
from types import TracebackType

import duckdb


SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    run_id VARCHAR, iteration INTEGER, started_at TIMESTAMPTZ DEFAULT current_timestamp,
    branch VARCHAR, parent_commit VARCHAR, commit_sha VARCHAR, status VARCHAR,
    cycle_speedup DOUBLE, scratch_reduction DOUBLE, combined_score DOUBLE,
    elapsed_seconds DOUBLE, model VARCHAR, effort VARCHAR, logs VARCHAR, error VARCHAR,
    PRIMARY KEY (run_id, iteration)
)
"""


class ResultsStore:
    """Start and finish writes commit separately; no transaction spans an agent run."""

    def __init__(self, path: Path):
        self.path = path.resolve()

    def __enter__(self) -> "ResultsStore":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = duckdb.connect(str(self.path))
        try:
            self._db.execute(SCHEMA)
        except BaseException:
            self._db.close()
            raise
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, traceback: TracebackType | None) -> None:
        self._db.close()

    def start_attempt(self, run_id: str, iteration: int, *, branch: str,
                      parent_commit: str, model: str, effort: str, logs: Path) -> None:
        self._db.execute(
            """INSERT INTO results
               (run_id, iteration, branch, parent_commit, status, model, effort, logs)
               VALUES ($run_id, $iteration, $branch, $parent_commit, 'running',
                       $model, $effort, $logs)""",
            dict(run_id=run_id, iteration=iteration, branch=branch,
                 parent_commit=parent_commit, model=model, effort=effort, logs=str(logs)),
        )

    def finish_attempt(self, run_id: str, iteration: int, *, commit_sha: str | None,
                       status: str, metrics: dict[str, float], elapsed_seconds: float,
                       error: str | None) -> None:
        self._db.execute(
            """UPDATE results SET commit_sha=$commit_sha, status=$status,
               cycle_speedup=$cycle_speedup, scratch_reduction=$scratch_reduction,
               combined_score=$combined_score, elapsed_seconds=$elapsed_seconds,
               error=$error WHERE run_id=$run_id AND iteration=$iteration""",
            dict(run_id=run_id, iteration=iteration, commit_sha=commit_sha, status=status,
                 cycle_speedup=metrics.get("cycle_speedup"),
                 scratch_reduction=metrics.get("scratch_reduction"),
                 combined_score=metrics.get("combined_score"),
                 elapsed_seconds=elapsed_seconds, error=error),
        )

    def recent_attempts(self, run_id: str, before_iteration: int,
                        limit: int = 5) -> list[tuple[int, str, float | None, str | None]]:
        return self._db.execute(
            """SELECT iteration, status, combined_score, error FROM results
               WHERE run_id=$run_id AND iteration<$before_iteration
               ORDER BY iteration DESC LIMIT $limit""",
            dict(run_id=run_id, before_iteration=before_iteration, limit=limit),
        ).fetchall()

"""SQLAlchemy models and persistence boundary for one DuckDB results database."""

from datetime import datetime
from pathlib import Path
from types import TracebackType

from sqlalchemy import DateTime, Double, Integer, String, URL, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


class Result(Base):
    """One baseline or attempt; (run_id, iteration) identifies its record.

    run_id: Unique invocation ID shared by the baseline and all its attempts.
    iteration: Zero for the baseline, then the sequential attempt number.
    started_at: Database timestamp when the attempt's running row was inserted.
    branch: Proposal branch; the baseline stores the configured starting ref.
    parent_commit: Commit from which this attempt's worktree was created.
    commit_sha: One proposal commit, baseline SHA, or null if none was committed.
    status: running/baseline/improved/rejected/no_change/failed/timeout/interrupted.
    cycle_speedup: Public geometric-mean cycle speedup multiplier, or null.
    scratch_reduction: Public geometric-mean scratch reduction multiplier, or null.
    combined_score: Public combined-score multiplier used to select the next parent.
    elapsed_seconds: Wall-clock duration from attempt start through cleanup.
    model: Requested Codex model (also recorded on the baseline, which uses none).
    effort: Requested reasoning effort: low, medium, high, or xhigh.
    logs: Absolute directory path containing prompt.txt, codex.log, and eval.log as available.
    error: Failure/interruption description, or null; full output is in the logs.
    """

    __tablename__ = "results"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    iteration: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(),
    )
    branch: Mapped[str | None] = mapped_column(String)
    parent_commit: Mapped[str | None] = mapped_column(String)
    commit_sha: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    cycle_speedup: Mapped[float | None] = mapped_column(Double)
    scratch_reduction: Mapped[float | None] = mapped_column(Double)
    combined_score: Mapped[float | None] = mapped_column(Double)
    elapsed_seconds: Mapped[float | None] = mapped_column(Double)
    model: Mapped[str | None] = mapped_column(String)
    effort: Mapped[str | None] = mapped_column(String)
    logs: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)


class ResultsStore:
    """Each method owns a short session; no transaction spans an agent run."""

    def __init__(self, path: Path):
        self.path = path.resolve()

    def __enter__(self) -> "ResultsStore":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(URL.create("duckdb", database=str(self.path)),
                                     poolclass=NullPool)
        try:
            Base.metadata.create_all(self._engine)
        except BaseException:
            self._engine.dispose()
            raise
        self._sessions = sessionmaker(self._engine)
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, traceback: TracebackType | None) -> None:
        self._engine.dispose()

    def start_attempt(self, run_id: str, iteration: int, *, branch: str,
                      parent_commit: str, model: str, effort: str, logs: Path) -> None:
        with self._sessions.begin() as session:
            session.add(Result(run_id=run_id, iteration=iteration, branch=branch,
                               parent_commit=parent_commit, status="running",
                               model=model, effort=effort, logs=str(logs)))

    def finish_attempt(self, run_id: str, iteration: int, *, commit_sha: str | None,
                       status: str, metrics: dict[str, float], elapsed_seconds: float,
                       error: str | None) -> None:
        with self._sessions.begin() as session:
            result = session.get(Result, (run_id, iteration))
            if result is None:
                raise KeyError(f"Unknown attempt: {run_id}/{iteration}")
            result.commit_sha = commit_sha
            result.status = status
            result.cycle_speedup = metrics.get("cycle_speedup")
            result.scratch_reduction = metrics.get("scratch_reduction")
            result.combined_score = metrics.get("combined_score")
            result.elapsed_seconds = elapsed_seconds
            result.error = error

    def recent_attempts(self, run_id: str, before_iteration: int,
                        limit: int = 5) -> list[tuple[int, str | None, float | None, str | None]]:
        query = (
            select(Result.iteration, Result.status, Result.combined_score, Result.error)
            .where(Result.run_id == run_id, Result.iteration < before_iteration)
            .order_by(Result.iteration.desc()).limit(limit)
        )
        with self._sessions() as session:
            return [tuple(row) for row in session.execute(query)]

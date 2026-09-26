"""Implemented by Codex (GPT-6).

Lifecycle integration: real Git and DuckDB; agent and evaluator are scripted."""

from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from openai_codex.generated.v2_all import GetAccountRateLimitsResponse

from autoresearch.config import load_config
from autoresearch.environment import GitRepository, git
from autoresearch.runner import research
from autoresearch.usage import UsageUnavailable
from tests.autoresearch.support import create_repository


def metrics(score):
    return {"cycle_speedup": score, "scratch_reduction": score, "combined_score": score}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.repo = create_repository(self.root / "repo")
        self.base = self.repo.resolve("main")
        self.db = self.root / "results.duckdb"
        self.available_usage = GetAccountRateLimitsResponse.model_validate({"rateLimits": {"primary": {"usedPercent": 0, "windowDurationMins": 300}}})
        usage_patch = patch("autoresearch.runner.read_usage", return_value=self.available_usage)
        self.read_usage = usage_patch.start()
        self.addCleanup(usage_patch.stop)

    def config(self, iterations):
        return load_config(overrides={"db": self.db, "iterations": iterations})

    def rows(self):
        with duckdb.connect(str(self.db), read_only=True) as db:
            return db.execute(
                "SELECT iteration, status, parent_commit, commit_sha, combined_score, error, logs FROM results ORDER BY iteration"
            ).fetchall()

    def assert_cleaned_up(self):
        self.assertEqual(git(self.repo.root, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(self.repo.resolve("main"), self.base)
        self.assertEqual(git(self.repo.root, "status", "--porcelain"), "")

    def test_improvement_and_rejection_use_best_parent_and_one_commit_each(self):
        seen = []

        def agent(command, path, log, timeout, prompt):
            with duckdb.connect(str(self.db), read_only=True) as db:
                self.assertEqual(db.execute("SELECT status FROM results ORDER BY iteration DESC LIMIT 1").fetchone(), ("running",))
            seen.append(git(path, "rev-parse", "HEAD"))
            with (path / "compiler.py").open("a") as output:
                output.write(f"# attempt {len(seen)}\n")
            self.assertIn("Never modify", prompt)
            self.assertIn("Only compiler.py may change", prompt)
            log.write_text("scripted agent\n")

        with (
            patch("autoresearch.runner.execute", side_effect=agent),
            patch("autoresearch.runner.evaluate", side_effect=[metrics(s) for s in (1, 2, 1.5, 3)]),
            redirect_stdout(StringIO()),
        ):
            research(self.config(3), self.repo.root)
        rows = self.rows()
        self.assertEqual([row[1] for row in rows], ["baseline", "improved", "rejected", "improved"])
        self.assertEqual(seen, [self.base, rows[1][3], rows[1][3]])
        for row in rows[1:]:
            self.assertEqual(git(self.repo.root, "rev-list", "--count", f"{row[2]}..{row[3]}"), "1")
            self.assertTrue((Path(row[6]) / "prompt.txt").is_file())
        self.assert_cleaned_up()

    def test_no_change_scope_violation_error_and_timeout_are_recorded(self):
        attempts = iter(("no_change", "scope", "error", "timeout"))

        def agent(command, path, log, timeout, prompt):
            action = next(attempts)
            if action == "scope":
                (path / "machine.py").write_text("tampered\n")
            elif action == "error":
                raise RuntimeError("agent failed")
            elif action == "timeout":
                raise subprocess.TimeoutExpired("codex", timeout)

        with (
            patch("autoresearch.runner.execute", side_effect=agent),
            patch("autoresearch.runner.evaluate", return_value=metrics(1)) as evaluate,
            redirect_stdout(StringIO()),
        ):
            research(self.config(4), self.repo.root)
        rows = self.rows()
        self.assertEqual([row[1] for row in rows], ["baseline", "no_change", "failed", "failed", "timeout"])
        self.assertTrue(all(row[3] is None for row in rows[1:]))
        self.assertTrue(all(row[4] is None for row in rows[1:]))
        evaluate.assert_called_once()
        self.assert_cleaned_up()

    def test_failed_evaluation_retains_proposal_commit(self):
        def agent(command, path, *args):
            (path / "compiler.py").write_text("# invalid compiler\n")

        with (
            patch("autoresearch.runner.execute", side_effect=agent),
            patch("autoresearch.runner.evaluate", side_effect=[metrics(1), RuntimeError("bad code")]),
            redirect_stdout(StringIO()),
        ):
            research(self.config(1), self.repo.root)
        row = self.rows()[1]
        self.assertEqual(row[1], "failed")
        self.assertIsNotNone(row[3])
        self.assertEqual(row[5], "bad code")
        self.assert_cleaned_up()

    def test_baseline_failure_is_recorded_and_stops_before_any_agent(self):
        with (
            patch("autoresearch.runner.execute") as agent,
            patch("autoresearch.runner.evaluate", side_effect=RuntimeError("bad baseline")),
            redirect_stdout(StringIO()),
            self.assertRaisesRegex(RuntimeError, "Baseline evaluation failed"),
        ):
            research(self.config(3), self.repo.root)
        agent.assert_not_called()
        self.assertEqual([(row[0], row[1]) for row in self.rows()], [(0, "failed")])
        self.assert_cleaned_up()

    def test_baseline_only_does_not_read_account_usage(self):
        with patch("autoresearch.runner.evaluate", return_value=metrics(1)), redirect_stdout(StringIO()):
            research(self.config(0), self.repo.root)
        self.read_usage.assert_not_called()
        self.assertEqual([(row[0], row[1]) for row in self.rows()], [(0, "baseline")])
        self.assert_cleaned_up()

    def test_low_weekly_quota_stops_before_creating_an_attempt(self):
        self.read_usage.return_value = GetAccountRateLimitsResponse.model_validate(
            {"rateLimits": {"secondary": {"usedPercent": 76, "windowDurationMins": 10080}}}
        )
        output = StringIO()
        with patch("autoresearch.runner.execute") as agent, patch("autoresearch.runner.evaluate", return_value=metrics(1)), redirect_stdout(output):
            research(self.config(3), self.repo.root)
        agent.assert_not_called()
        self.assertEqual([(row[0], row[1]) for row in self.rows()], [(0, "baseline")])
        self.assertEqual(git(self.repo.root, "branch", "--list", "autoresearch/*"), "")
        self.assertIn("weekly: 24% remaining", output.getvalue())
        self.assertIn("Best: main", output.getvalue())
        self.assert_cleaned_up()

    def test_fresh_quota_check_stops_after_a_completed_attempt(self):
        self.read_usage.side_effect = [
            self.available_usage,
            GetAccountRateLimitsResponse.model_validate({"rateLimits": {"primary": {"usedPercent": 96, "windowDurationMins": 300}}}),
        ]
        with (
            patch("autoresearch.runner.execute") as agent,
            patch("autoresearch.runner.evaluate", return_value=metrics(1)),
            redirect_stdout(StringIO()),
        ):
            research(self.config(3), self.repo.root)
        agent.assert_called_once()
        self.assertEqual(self.read_usage.call_count, 2)
        self.read_usage.assert_called_with(cwd=self.repo.root)
        self.assertEqual([(row[0], row[1]) for row in self.rows()], [(0, "baseline"), (1, "no_change")])
        self.assert_cleaned_up()

    def test_unavailable_usage_aborts_before_any_agent(self):
        self.read_usage.side_effect = UsageUnavailable("quota service unavailable")
        with (
            patch("autoresearch.runner.execute") as agent,
            patch("autoresearch.runner.evaluate", return_value=metrics(1)),
            redirect_stdout(StringIO()),
            self.assertRaisesRegex(UsageUnavailable, "quota service unavailable"),
        ):
            research(self.config(3), self.repo.root)
        agent.assert_not_called()
        self.assertEqual([(row[0], row[1]) for row in self.rows()], [(0, "baseline")])
        self.assert_cleaned_up()

    def test_interruption_is_durable_and_propagates(self):
        with (
            patch("autoresearch.runner.execute", side_effect=KeyboardInterrupt),
            patch("autoresearch.runner.evaluate", return_value=metrics(1)),
            redirect_stdout(StringIO()),
            self.assertRaises(KeyboardInterrupt),
        ):
            research(self.config(2), self.repo.root)
        self.assertEqual(self.rows()[1][1], "interrupted")
        self.assert_cleaned_up()

    def test_evaluator_mutation_is_rejected(self):
        def evaluator(path, log, timeout):
            (path / "compiler.py").write_text("# evaluation tampered with compiler\n")
            return metrics(100)

        with (
            patch("autoresearch.runner.evaluate", side_effect=evaluator),
            redirect_stdout(StringIO()),
            self.assertRaisesRegex(RuntimeError, "Evaluation modified"),
        ):
            research(self.config(0), self.repo.root)
        self.assertEqual(self.rows()[0][1], "failed")
        self.assert_cleaned_up()

    def test_cleanup_failure_does_not_promote_proposal_or_record_success(self):
        original_worktree = GitRepository.worktree

        @contextmanager
        def failing_cleanup(repository, commit, branch=None):
            with original_worktree(repository, commit, branch) as path:
                yield path
            if branch and branch.endswith(("/0001", "/0002")):
                raise RuntimeError("cleanup failed")

        attempts = iter(("# first candidate\n", None, "# third candidate\n"))

        def agent(command, path, *args):
            contents = next(attempts)
            if contents is not None:
                (path / "compiler.py").write_text(contents)

        with (
            patch.object(GitRepository, "worktree", failing_cleanup),
            patch("autoresearch.runner.execute", side_effect=agent),
            patch("autoresearch.runner.evaluate", side_effect=[metrics(s) for s in (1, 2, 1.5)]),
            redirect_stdout(StringIO()),
        ):
            research(self.config(3), self.repo.root)
        rows = self.rows()
        self.assertEqual([row[1] for row in rows], ["baseline", "failed", "failed", "improved"])
        self.assertEqual([row[2] for row in rows[1:]], [self.base] * 3)
        self.assertEqual([row[5] for row in rows[1:3]], ["cleanup failed"] * 2)
        self.assert_cleaned_up()

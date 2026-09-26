"""Real temporary DuckDB databases; no agent calls."""

from pathlib import Path
import tempfile
import unittest

import duckdb

from autoresearch.database import ResultsStore


class ResultsStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "nested" / "results.duckdb"

    def start(self, store, iteration=0, run_id="run"):
        store.start_attempt(run_id, iteration, branch="branch", parent_commit="parent",
                            model="model", effort="high", logs=Path("logs"))

    def test_running_row_survives_failure_and_is_visible_before_store_closes(self):
        with self.assertRaisesRegex(RuntimeError, "crash"):
            with ResultsStore(self.path) as store:
                self.start(store)
                with duckdb.connect(str(self.path)) as observer:
                    self.assertEqual(observer.execute("SELECT status FROM results").fetchone(),
                                     ("running",))
                raise RuntimeError("crash")
        with ResultsStore(self.path) as store:
            self.assertEqual(store.recent_attempts("run", 1), [(0, "running", None, None)])

    def test_finish_round_trip_and_failure_nulls(self):
        with ResultsStore(self.path) as store:
            self.start(store)
            self.start(store, 1)
            store.finish_attempt("run", 0, commit_sha="sha", status="baseline",
                                 metrics={"combined_score": 1.25, "cycle_speedup": 1.5,
                                          "scratch_reduction": 1.1},
                                 elapsed_seconds=2.5, error=None)
            store.finish_attempt("run", 1, commit_sha=None, status="failed", metrics={},
                                 elapsed_seconds=3, error="can't parse 'metrics'")
        with duckdb.connect(str(self.path), read_only=True) as db:
            rows = db.execute("SELECT commit_sha, status, cycle_speedup, scratch_reduction, "
                              "combined_score, elapsed_seconds, error, started_at "
                              "FROM results ORDER BY iteration").fetchall()
        self.assertEqual(rows[0][:7], ("sha", "baseline", 1.5, 1.1, 1.25, 2.5, None))
        self.assertEqual(rows[1][:7], (None, "failed", None, None, None, 3.0,
                                      "can't parse 'metrics'"))
        self.assertIsNotNone(rows[0][7])

    def test_recent_attempts_are_scoped_ordered_and_bounded(self):
        with ResultsStore(self.path) as store:
            for iteration in range(8):
                self.start(store, iteration)
            self.start(store, 9, "other")
            self.assertEqual([row[0] for row in store.recent_attempts("run", 7)],
                             [6, 5, 4, 3, 2])
            self.assertEqual(store.recent_attempts("missing", 10), [])
            self.assertEqual([row[0] for row in store.recent_attempts("run", 4, limit=2)],
                             [3, 2])

    def test_duplicate_attempt_does_not_overwrite_existing_record(self):
        with ResultsStore(self.path) as store:
            self.start(store)
            with self.assertRaises(Exception):
                self.start(store)
            self.assertEqual(store.recent_attempts("run", 1), [(0, "running", None, None)])

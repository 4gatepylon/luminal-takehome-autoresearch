"""Check ordering search caching, legal execution, exhaustion, and sampling probabilities."""

import unittest
from unittest.mock import patch

import numpy as np

import machine
from compiler import compilation as compiler_compilation
from compiler.reordering import OrderingAttempt, OrderingOptimizer


class OrderingSearchContractTests(unittest.TestCase):
    def setUp(self):
        self.program = {
            "name": "independent_stores", "buffers": {"out": 2},
            "operations": [
                {"id": 0, "op": "const", "dest": "a", "value": 7},
                {"id": 1, "op": "const", "dest": "b", "value": 9},
                {"id": 2, "op": "store", "args": ["a"], "buffer": "out", "offset": 0},
                {"id": 3, "op": "store", "args": ["b"], "buffer": "out", "offset": 1},
            ],
            "cases": [{"out": [0, 0]}],
        }

    def test_evaluations_are_unique_and_valid_and_exhausted_rows_are_retired(self):
        with patch.object(
            compiler_compilation, "compile_with_ordering",
            wraps=compiler_compilation.compile_with_ordering,
        ) as compile_ordering:
            optimizer = OrderingOptimizer(self.program)
            with self.assertWarnsRegex(RuntimeWarning, "No unseen reachable ordering"):
                best_ordering = optimizer.optimize_ordering_for_greedy_scheduler(128)
            evaluated_orderings = [call.args[1] for call in compile_ordering.call_args_list]
            self.assertEqual(len(evaluated_orderings), len(set(evaluated_orderings)))
            optimizer._evaluate_single(best_ordering)
            self.assertEqual(compile_ordering.call_count, len(evaluated_orderings))
        self.assertTrue(all(not attempt.can_reorder for attempt in optimizer.database.values()))
        self.assertIsNone(optimizer._sample_previously_attempted_ordering())
        for ordering in optimizer.database:
            compilation = compiler_compilation.compile_with_ordering(self.program, ordering)
            machine.check_compilation(self.program, compilation)
            machine.check_case(self.program, compilation, self.program["cases"][0])
        best = optimizer.database[best_ordering]
        self.assertEqual(best.speedup * best.memory_improvement, max(
            attempt.speedup * attempt.memory_improvement for attempt in optimizer.database.values()
        ))
        with self.assertRaisesRegex(RuntimeError, "No unseen reachable ordering"):
            optimizer.optimize_ordering_for_greedy_scheduler(1, crash_on_sampling_failure=True)

    def test_inner_retry_limit_and_retired_rows(self):
        optimizer = OrderingOptimizer(self.program)
        optimizer._evaluate_single((1, 0, 2, 3))
        with patch.object(optimizer, "_sample_unseen_reachable_ordering", return_value=None) as sample:
            with self.assertWarns(RuntimeWarning):
                optimizer.optimize_ordering_for_greedy_scheduler(1, max_inner_iterations=1)
            self.assertEqual(sample.call_count, 1)
            self.assertEqual(sum(attempt.can_reorder for attempt in optimizer.database.values()), 1)
            with self.assertWarns(RuntimeWarning):
                optimizer.optimize_ordering_for_greedy_scheduler(1, max_inner_iterations=32)
            self.assertEqual(sample.call_count, 2)
            self.assertNotEqual(sample.call_args_list[0], sample.call_args_list[1])

    def test_softmax_uses_geometric_mean_temperature_and_only_eligible_rows(self):
        optimizer = OrderingOptimizer(self.program, sample_strategy="softmax")
        optimizer.database = {
            (0,): OrderingAttempt(1, 1, (0,)),
            (1,): OrderingAttempt(4, 1, (1,)),
            (2,): OrderingAttempt(100, 100, (2,), can_reorder=False),
        }
        for temperature in (1.0, 2.0, 0.001):
            with self.subTest(temperature=temperature):
                if temperature != 1.0:
                    optimizer.sample_strategy_kwargs["temperature"] = temperature
                with patch.object(np.random, "choice", return_value=0) as choose:
                    self.assertEqual(optimizer._sample_previously_attempted_ordering().ordering, (0,))
                weights = np.exp(np.array([-1.0, 0.0]) / temperature)
                self.assertEqual(choose.call_args.args, (2,))
                np.testing.assert_allclose(choose.call_args.kwargs["p"], weights / weights.sum())
        optimizer.sample_strategy = "uniform_at_random"
        with patch.object(np.random, "choice", return_value=0) as choose:
            optimizer._sample_previously_attempted_ordering()
        self.assertIsNone(choose.call_args.kwargs["p"])
        for temperature in (0, -1, float("nan"), float("inf")):
            with self.subTest(temperature=temperature), self.assertRaises(ValueError):
                OrderingOptimizer(self.program, sample_strategy="softmax", sample_strategy_kwargs={"temperature": temperature})

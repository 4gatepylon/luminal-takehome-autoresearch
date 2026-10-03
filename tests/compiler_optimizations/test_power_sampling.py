"""Check cutoff power sampling probabilities, parameter validation, and empty support."""

import unittest
from unittest.mock import patch

import numpy as np

from compiler.reordering import OrderingAttempt, OrderingOptimizer


class PowerSamplingTests(unittest.TestCase):
    def setUp(self):
        self.program = {
            "name": "power_sampling", "buffers": {"out": 1},
            "operations": [
                {"id": 0, "op": "const", "dest": "a", "value": 7},
                {"id": 1, "op": "store", "args": ["a"], "buffer": "out", "offset": 0},
            ],
            "cases": [{"out": [0]}],
        }
        self.optimizer = OrderingOptimizer(self.program, sample_strategy="power")
        self.optimizer.database = {
            (0,): OrderingAttempt(1, 1, (0,)),
            (1,): OrderingAttempt(4, 1, (1,)),
            (2,): OrderingAttempt(9, 1, (2,)),
            (3,): OrderingAttempt(100, 100, (3,), can_reorder=False),
        }

    def test_geometric_scores_cutoff_power_and_exhausted_rows(self):
        examples = [
            ({}, [1, 4, 9]),
            ({"cutoff": 1, "power": 2}, [0, 1, 4]),
            ({"cutoff": 1.5, "power": 0.5}, [0, np.sqrt(0.5), np.sqrt(1.5)]),
            ({"cutoff": -1, "power": 1}, [2, 3, 4]),
            ({"power": 1e6}, [0, 0, 1]),
        ]
        for kwargs, expected_weights in examples:
            with self.subTest(kwargs=kwargs), patch.object(np.random, "choice", return_value=2) as choose:
                self.optimizer.sample_strategy_kwargs = kwargs
                self.assertEqual(self.optimizer._sample_previously_attempted_ordering().ordering, (2,))
                self.assertEqual(choose.call_args.args, (3,))
                np.testing.assert_allclose(
                    choose.call_args.kwargs["p"], np.array(expected_weights) / sum(expected_weights)
                )

    def test_excluded_support_uses_sampling_failure_policy(self):
        self.optimizer.sample_strategy_kwargs = {"cutoff": 3}
        self.assertIsNone(self.optimizer._sample_previously_attempted_ordering())
        with self.assertWarns(RuntimeWarning):
            self.optimizer.optimize_ordering_for_greedy_scheduler(4)
        with self.assertRaises(RuntimeError):
            self.optimizer.optimize_ordering_for_greedy_scheduler(4, crash_on_sampling_failure=True)
        self.assertTrue(self.optimizer.database[(2,)].can_reorder)

    def test_invalid_parameters_are_rejected(self):
        for kwargs in ({"power": 0}, {"power": -1}, {"power": float("inf")},
                       {"power": float("nan")}, {"cutoff": float("inf")}, {"cutoff": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                OrderingOptimizer(self.program, sample_strategy="power", sample_strategy_kwargs=kwargs)

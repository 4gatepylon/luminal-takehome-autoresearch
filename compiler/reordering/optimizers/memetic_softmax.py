"""Ordering search with uniform or temperature-controlled softmax sampling.

Reference: https://chatgpt.com/share/6ac08d07-6048-83e8-9077-34bba9f773bd
"""

from __future__ import annotations

from dataclasses import dataclass
import warnings
from typing import Any, Literal

import numpy as np
from tqdm import tqdm

import machine

from ... import compilation as compiler_compilation
from ..lib import OperationDependencies


@dataclass
class OrderingAttempt:
    speedup: float
    memory_improvement: float
    ordering: tuple[int, ...]
    can_reorder: bool = True


class OrderingOptimizer:
    def __init__(
        self, program: dict[str, Any],
        scratch_allocation_strategy: Literal[
            "any", "first-fit", "disjoint", "hierarchical-first-fit"
        ] = "any",
        verbose: bool = False,
        sample_strategy: Literal["uniform_at_random", "softmax"] = "uniform_at_random",
        sample_strategy_kwargs: dict[str, float] | None = None,
    ) -> None:
        if sample_strategy not in ("uniform_at_random", "softmax"):
            raise ValueError(f"Unsupported sample strategy: {sample_strategy}")
        self.sample_strategy = sample_strategy
        self.sample_strategy_kwargs = dict(sample_strategy_kwargs or {})
        temperature = self.sample_strategy_kwargs.get("temperature", 1.0)
        if sample_strategy == "softmax" and (not np.isfinite(temperature) or temperature <= 0):
            raise ValueError("Softmax temperature must be finite and positive")
        self.program = program
        self.verbose = verbose
        self.scratch_allocation_strategy = scratch_allocation_strategy
        self.dependencies = OperationDependencies(program)
        baseline: dict[str, Any] = machine.serial_compile(program)
        self.baseline_cycles = len(baseline["bundles"])
        self.baseline_memory = machine.scratch_footprint(program, baseline)
        self.database: dict[tuple[int, ...], OrderingAttempt] = {}
        self._evaluate_single(tuple(range(len(program["operations"]))))

    def _evaluate_single(self, ordering: tuple[int, ...]) -> OrderingAttempt:
        """Evaluate an ordering once, caching the result under its hashed tuple key."""
        if ordering in self.database:
            return self.database[ordering]
        compilation = compiler_compilation.compile_with_ordering(
            self.program, ordering, self.scratch_allocation_strategy, self.verbose
        )
        cycles = machine.check_compilation(self.program, compilation)
        memory = machine.scratch_footprint(self.program, compilation)
        attempt = OrderingAttempt(self.baseline_cycles / cycles, self.baseline_memory / memory, ordering)
        self.database[ordering] = attempt
        return attempt

    def _sample_previously_attempted_ordering(self) -> OrderingAttempt | None:
        """Sample an eligible attempt using the selected distribution, or return None."""
        attempts = [attempt for attempt in self.database.values() if attempt.can_reorder]
        if not attempts:
            return None
        probabilities = None
        if self.sample_strategy == "softmax":
            scores = np.sqrt([attempt.speedup * attempt.memory_improvement for attempt in attempts])
            temperature = self.sample_strategy_kwargs.get("temperature", 1.0)
            weights = np.exp((scores - scores.max()) / temperature)
            probabilities = weights / weights.sum()
        return attempts[np.random.choice(len(attempts), p=probabilities)]

    def _sample_unseen_reachable_ordering(self, previous_ordering: tuple[int, ...]) -> tuple[int, ...] | None:
        """Sample an unseen legal earlier move, or return None if all are exhausted."""
        for current_index in np.random.permutation(len(previous_ordering)):
            operation = self.program["operations"][previous_ordering[current_index]]
            earliest_index_incl = self.dependencies.latest_dependency(operation, previous_ordering) + 1
            for destination_index in np.random.permutation(range(earliest_index_incl, current_index)):
                candidate_ordering = list(previous_ordering)
                candidate_ordering.insert(destination_index, candidate_ordering.pop(current_index))
                ordering = tuple(candidate_ordering)
                if ordering not in self.database:
                    return ordering
        return None

    def optimize_ordering_for_greedy_scheduler(
        self, n_optimization_iterations: int = 128, *, max_inner_iterations: int = 32,
        crash_on_sampling_failure: bool = False,
    ) -> tuple[int, ...]:
        """Search unseen orderings; on sampling failure, raise or warn and stop."""
        for _ in tqdm(range(n_optimization_iterations), desc="Optimizing ordering"):
            ordering = None
            for _ in range(max_inner_iterations):
                previous_attempt = self._sample_previously_attempted_ordering()
                if previous_attempt is None:
                    break
                ordering = self._sample_unseen_reachable_ordering(previous_attempt.ordering)
                if ordering is not None:
                    break
                previous_attempt.can_reorder = False
            if ordering is None:
                message = f"No unseen reachable ordering found within {max_inner_iterations} attempts; stopping search."
                if crash_on_sampling_failure:
                    raise RuntimeError(message)
                warnings.warn(message, RuntimeWarning, stacklevel=2)
                break
            self._evaluate_single(ordering)
        return max(self.database.values(), key=lambda attempt: attempt.speedup * attempt.memory_improvement).ordering

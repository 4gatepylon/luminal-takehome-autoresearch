"""Custom schedulers generate dependency-preserving tuples of original operation IDs.

Register a generator in SCHEDULER_NAME2ORDERINGS_FN to expose it to compilation
and benchmarking. Compilation compares its candidates with source order using
cycles times allocated scratch words, and restores original IDs in the result.
"""

from collections.abc import Callable, Iterable

from .dag_pressure_codex import dag_orderings
from .beam_pressure_codex import candidate_orderings


SCHEDULER_NAME2ORDERINGS_FN: dict[str, Callable[[dict], Iterable[tuple[int, ...]]]] = {
    "dag-pressure-codex": dag_orderings,
    "beam-pressure-codex": candidate_orderings,
}

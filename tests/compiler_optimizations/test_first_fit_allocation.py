"""Tests allocate_scratch_first_fit ordering, alignment, and scratch reuse directly.

TODO(hadriano) no human has read these unit tests.
"""

import unittest
from unittest.mock import patch

from compiler.allocation import allocate_scratch_first_fit
import machine


class FirstFitAllocationTests(unittest.TestCase):
    def test_first_fit_allocation_order_and_reuse(self):
        # Each value is (name, width, write_cycle_incl, last_live_cycle_incl).
        examples = [
            ("time before width", [("z", 8, 4, 6), ("a", 1, 1, 6)], {"a": 0, "z": 8}, 256),
            ("width before name", [("a", 1, 4, 6), ("z", 8, 4, 6)], {"z": 0, "a": 8}, 256),
            ("name before source order", [("z", 1, 1, 2), ("a", 1, 1, 2)], {"a": 0, "z": 1}, 256),
            ("reuse after final read", [("input", 8, 4, 5), ("output", 1, 6, 6)], {"input": 0, "output": 0}, 256),
            ("no reuse on final read", [("input", 8, 4, 5), ("output", 1, 5, 5)], {"input": 0, "output": 8}, 256),
            ("simultaneous unused writes", [("a", 1, 3, 3), ("b", 1, 3, 3)], {"a": 0, "b": 1}, 256),
            (
                "scalars fill alignment holes below a later vector",
                [("vec1", 8, 1, 9), ("scalar1", 1, 2, 9), ("vec2", 8, 3, 9)]
                + [(f"scalar{index}", 1, 4, 9) for index in range(2, 9)],
                {"vec1": 0, "vec2": 16}
                | {f"scalar{index}": 7 + index for index in range(1, 9)},
                256,
            ),
        ]
        for name, values, expected_value_name2scratch_address, scratch_words in examples:
            with self.subTest(name=name), patch.object(machine, "SCRATCH_WORDS", scratch_words):
                program = {"operations": [
                    {"dest": value_name, "op": "vload" if width == 8 else "const"}
                    for value_name, width, _, _ in values
                ]}
                value_name2lifetime_incl = {
                    value_name: (write_cycle_incl, last_live_cycle_incl)
                    for value_name, _, write_cycle_incl, last_live_cycle_incl in values
                }
                self.assertEqual(
                    allocate_scratch_first_fit(program, value_name2lifetime_incl, mode="default"),
                    expected_value_name2scratch_address,
                )


if __name__ == "__main__":
    unittest.main()

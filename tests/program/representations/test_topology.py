"""Tests for generic topological layering."""

import unittest

from program.representations.graphviz._topology import topological_layers


class TopologicalLayersTests(unittest.TestCase):
    def test_longest_path_and_stable_order(self):
        self.assertEqual(
            topological_layers(
                ["end", "right", "isolated", "left", "root"],
                [("root", "left"), ("root", "right"),
                 ("left", "end"), ("right", "end"), ("root", "end")],
            ),
            [["isolated", "root"], ["right", "left"], ["end"]],
        )

    def test_duplicates(self):
        self.assertEqual(topological_layers([1, 1, 2], [(1, 2), (1, 2)]), [[1], [2]])

    def test_empty(self):
        self.assertEqual(topological_layers([], []), [])

    def test_cycles(self):
        for edges in [[(1, 1)], [(1, 2), (2, 1)]]:
            with self.subTest(edges=edges), self.assertRaisesRegex(ValueError, "cycle"):
                topological_layers([0, 1, 2], edges)

    def test_unknown_endpoint(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            topological_layers([1], [(1, 2)])

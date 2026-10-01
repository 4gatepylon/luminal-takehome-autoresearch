"""SVG output, one-way decoding, and validation before rendering."""

from copy import deepcopy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from machine import load_program
from program.representations import Representation
from program.representations.graphviz import GraphvizRepresentation


class GraphvizRepresentationTests(unittest.TestCase):
    def test_decode_is_explicitly_unsupported(self):
        for format in ("svg", "dot"):
            with self.subTest(format=format):
                representation = GraphvizRepresentation(format=format)
                self.assertIsInstance(representation, Representation)
                with self.assertRaisesRegex(NotImplementedError, "cannot be decoded"):
                    representation.decode("visualization")

    def test_dot_output_does_not_require_graphviz(self):
        program = load_program("programs/json/03_vector_axpy.json")
        with patch("program.representations.graphviz._graphviz.shutil.which", return_value=None):
            source = GraphvizRepresentation(format="dot").encode(program)
        self.assertTrue(source.startswith("digraph SSA {"))
        self.assertIn("op0 -> v0", source)

    def test_unknown_output_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "svg.*dot"):
            GraphvizRepresentation(format="png")

    def test_invalid_program_is_rejected_before_rendering(self):
        with patch("program.representations.graphviz.representation.render_svg") as render:
            with self.assertRaises(ValueError):
                GraphvizRepresentation().encode({})
            render.assert_not_called()

    def test_missing_graphviz_has_actionable_error(self):
        program = load_program("programs/json/03_vector_axpy.json")
        with patch("program.representations.graphviz._graphviz.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "Graphviz is required"):
                GraphvizRepresentation().encode(program)

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_all_programs_render_without_mutation(self):
        representation = GraphvizRepresentation()
        paths = sorted(Path("programs/json").glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(program=path.name):
                program = load_program(path)
                before = deepcopy(program)
                text = representation.encode(program)
                self.assertIsInstance(text, str)
                svg = ET.fromstring(text)
                self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
                nodes = [node for node in svg.iter() if node.get("class") == "node"]
                self.assertEqual(
                    len(nodes),
                    len(program["operations"]) + sum("dest" in op for op in program["operations"]),
                )
                self.assertEqual(program, before)

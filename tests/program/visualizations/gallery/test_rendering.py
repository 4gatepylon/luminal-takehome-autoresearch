"""Check Graphviz output for public programs and unusual SSA names."""

from pathlib import Path
import shutil
import unittest
import xml.etree.ElementTree as ET

from machine import load_program
from program.representations.graphviz import GraphvizRepresentation


@unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
class VisualizationTests(unittest.TestCase):
    def render(self, program):
        return ET.fromstring(GraphvizRepresentation().encode(program))

    def test_all_public_programs(self):
        for path in sorted(Path("programs/json").glob("*.json")):
            with self.subTest(program=path.name):
                program = load_program(path)
                svg = self.render(program)
                nodes = [node for node in svg.iter() if node.get("class") == "node"]
                operations = program["operations"]
                self.assertEqual(
                    len(nodes), len(operations) + sum("dest" in op for op in operations)
                )

    def test_repeated_operands_and_literal_names(self):
        name = 'a"\\N<&>'
        program = {
            "name": "Escaping <&>",
            "buffers": {"out": 1},
            "cases": [{"out": [0]}],
            "operations": [
                {"id": 0, "op": "const", "dest": name, "value": 1},
                {"id": 1, "op": "sub", "dest": "result", "args": [name, name]},
            ],
        }
        svg = self.render(program)
        edges = [node for node in svg.iter() if node.get("class") == "edge"]
        self.assertEqual(len(edges), 4)
        labels = [node.text for node in svg.iter() if node.tag.endswith("}text")]
        self.assertIn(name, labels)
        self.assertIn("1", labels)
        self.assertIn("2", labels)

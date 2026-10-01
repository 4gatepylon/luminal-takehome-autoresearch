"""JSON round trips and validation."""

from copy import deepcopy
from pathlib import Path
import unittest

from machine import load_program
from program.representations import Representation
from program.representations.json import JsonRepresentation


class JsonRepresentationTests(unittest.TestCase):
    def test_all_programs_round_trip_without_mutation(self):
        representation = JsonRepresentation()
        self.assertIsInstance(representation, Representation)
        paths = sorted(Path("programs/json").glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(program=path.name):
                program = load_program(path)
                program["metadata"] = {"unicode": "λ", "values": [None, True, 1.25]}
                before = deepcopy(program)
                text = representation.encode(program)
                self.assertIsInstance(text, str)
                self.assertEqual(representation.decode(text), before)
                self.assertEqual(program, before)

    def test_invalid_input_is_rejected(self):
        representation = JsonRepresentation()
        for text in ("not JSON", "[]", "{}"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                representation.decode(text)
        with self.assertRaises(ValueError):
            representation.encode({})

    def test_ambiguous_or_nonstandard_json_is_rejected(self):
        representation = JsonRepresentation()
        source = representation.encode(load_program("programs/json/03_vector_axpy.json"))
        for metadata in ('{"key": 1, "key": 2}', '{"value": NaN}', '{"value": Infinity}'):
            text = '{"metadata": ' + metadata + ',' + source[1:]
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                representation.decode(text)

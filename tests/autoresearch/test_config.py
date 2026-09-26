"""YAML hydration and validation, independent of Git, databases, or Codex."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from autoresearch.config import config_yaml, load_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.yaml"

    def test_defaults_and_partial_yaml_then_explicit_overrides(self):
        defaults = load_config()
        self.path.write_text("iterations: 3\neffort: high\n")
        config = load_config(self.path, overrides={"iterations": 0, "model": None})
        self.assertEqual(config.iterations, 0)
        self.assertEqual(config.effort, "high")
        self.assertEqual(config.model, defaults.model)
        self.assertEqual(config.db, Path(".autoresearch/results.duckdb"))
        self.assertEqual(load_config().iterations, defaults.iterations)
        with self.assertRaises(FrozenInstanceError):
            config.iterations = 5

    def test_hydrated_yaml_round_trips(self):
        config = load_config(overrides={"db": Path("results with spaces.duckdb")})
        self.path.write_text(config_yaml(config))
        self.assertEqual(load_config(self.path), config)

    def test_invalid_values_and_unknown_fields_are_rejected(self):
        for contents in ("iterations: -1", "iterations: true", "iterations: 1.5",
                         "eval_timeout: 0", "codex_timeout: .inf", "eval_timeout: .nan",
                         "effort: extreme", "model: ''", "base: ' '",
                         "iteratons: 10", "iterations: null", "- not\n- a mapping"):
            with self.subTest(contents=contents):
                self.path.write_text(contents)
                with self.assertRaises(ValidationError):
                    load_config(self.path)

    def test_empty_yaml_uses_defaults(self):
        self.path.write_text("")
        self.assertEqual(load_config(self.path), load_config())

    def test_missing_or_malformed_yaml_fails(self):
        with self.assertRaises(FileNotFoundError):
            load_config(self.path)
        self.path.write_text("iterations: [")
        with self.assertRaises(Exception):
            load_config(self.path)

    def test_yaml_cannot_construct_python_objects(self):
        self.path.write_text("!!python/object/apply:builtins.str [123]")
        with self.assertRaises(Exception):
            load_config(self.path)

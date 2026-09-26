"""Click boundary tests; research and Git discovery are mocked."""

from pathlib import Path
import unittest
from unittest.mock import patch

from click.testing import CliRunner
from pydantic_yaml import parse_yaml_raw_as

from autoresearch.cli import main
from autoresearch.config import ResearchConfig
from autoresearch.environment import GitRepository


class CliTests(unittest.TestCase):
    def setUp(self):
        self.cli = CliRunner()

    def test_help_and_show_config_need_no_codex_or_repository(self):
        with self.cli.isolated_filesystem(), patch("autoresearch.cli.shutil.which") as which:
            result = self.cli.invoke(main, ["--help"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("--config", result.output)
            result = self.cli.invoke(main, ["--show-config"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(parse_yaml_raw_as(ResearchConfig, result.output).iterations, 10)
            which.assert_not_called()

    def test_yaml_and_cli_precedence_reaches_runner(self):
        with self.cli.isolated_filesystem(), \
                patch("autoresearch.cli.shutil.which", return_value="codex"), \
                patch("autoresearch.environment.GitRepository.discover",
                      return_value=GitRepository(Path("/repo"))), \
                patch("autoresearch.runner.research") as research:
            Path("run.yaml").write_text("iterations: 4\neffort: high\n")
            result = self.cli.invoke(main, ["--config", "run.yaml", "--iterations", "0"])
            self.assertEqual(result.exit_code, 0, result.output)
            config, repo = research.call_args.args
            self.assertEqual((config.iterations, config.effort, repo), (0, "high", Path("/repo")))

    def test_bad_config_fails_before_tools_run(self):
        with self.cli.isolated_filesystem(), patch("autoresearch.cli.shutil.which") as which:
            for text in ("iterations: -1", "unknown: true", "iterations: ["):
                with self.subTest(text=text):
                    Path("bad.yaml").write_text(text)
                    result = self.cli.invoke(main, ["--config", "bad.yaml"])
                    self.assertNotEqual(result.exit_code, 0)
                    self.assertIn("Invalid configuration", result.output)
            which.assert_not_called()

    def test_bad_cli_values_and_missing_yaml(self):
        for args in (["--iterations", "-1"], ["--eval-timeout", "0"],
                     ["--effort", "extreme"], ["--config", "/missing/config.yaml"]):
            with self.subTest(args=args):
                result = self.cli.invoke(main, args)
                self.assertEqual(result.exit_code, 2, result.output)

    def test_baseline_still_requires_codex_for_the_evaluation_sandbox(self):
        with patch("autoresearch.cli.shutil.which", return_value=None):
            result = self.cli.invoke(main, ["--iterations", "0"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Install the Codex CLI", result.output)

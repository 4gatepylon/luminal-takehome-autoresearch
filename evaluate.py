"""Run public tests and scoring from Python or the command line."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from typing import TextIO

from compiler_loader import DEFAULT_COMPILER_PATH
from score import score
from tests.test_public_programs import PublicProgramTests


def test(compiler_path: str | Path = DEFAULT_COMPILER_PATH, *, verbosity: int = 2, stream: TextIO | None = None) -> unittest.TestResult:
    """Run the public unit tests in-process and return their result without exiting."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("tests.test_machine")
    compiler_tests = loader.loadTestsFromTestCase(PublicProgramTests)
    for case in compiler_tests:
        case.compiler_path = compiler_path
    suite.addTests(compiler_tests)
    return unittest.TextTestRunner(stream=stream, verbosity=verbosity).run(suite)


def eval(compiler_path: str | Path = DEFAULT_COMPILER_PATH, *, verbose: bool = False) -> dict[str, float] | None:
    """Run tests, then return score metrics; return None if tests fail."""
    if not test(compiler_path).wasSuccessful():
        return None
    return score(compiler_path, verbose=verbose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("test", "score", "eval"))
    parser.add_argument("--compiler-path", type=Path, default=DEFAULT_COMPILER_PATH, help="compiler Python file (default: work/compiler.py)")
    args = parser.parse_args(argv)
    if args.command == "test":
        return 0 if test(args.compiler_path).wasSuccessful() else 1
    if args.command == "eval":
        return 0 if eval(args.compiler_path, verbose=True) is not None else 1
    score(args.compiler_path, verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

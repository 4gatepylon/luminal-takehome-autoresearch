"""Run public tests and scoring from Python or the command line."""

from __future__ import annotations

import argparse
import unittest
from typing import TextIO

from score import score


def test(*, verbosity: int = 2, stream: TextIO | None = None) -> unittest.TestResult:
    """Run the public unit tests in-process and return their result without exiting."""
    suite = unittest.TestLoader().loadTestsFromNames(
        ["tests.test_machine", "tests.test_public_programs"]
    )
    return unittest.TextTestRunner(stream=stream, verbosity=verbosity).run(suite)


def eval(*, verbose: bool = False) -> dict[str, float] | None:
    """Run tests, then return score metrics; return None if tests fail."""
    if not test().wasSuccessful():
        return None
    return score(verbose=verbose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("test", "score", "eval"))
    args = parser.parse_args(argv)
    if args.command == "test":
        return 0 if test().wasSuccessful() else 1
    if args.command == "eval":
        return 0 if eval(verbose=True) is not None else 1
    score(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compatibility entry point for the shared sandboxed compiler scorer."""

from evaluate import score


def main() -> int:
    score(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

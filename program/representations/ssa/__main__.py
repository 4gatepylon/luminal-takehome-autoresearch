"""Run the existing SSA conversion CLI from its new package location."""

from program.representations.ssa._codec import main


if __name__ == "__main__":
    raise SystemExit(main())

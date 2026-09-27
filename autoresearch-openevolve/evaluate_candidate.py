"""Call the shared evaluation API inside the sandbox and emit only JSON metrics.

The API must execute the compiler in-process because the sandbox denies forks.
"""

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from evaluate import eval as evaluate_compiler


def main() -> int:
    compiler_filepath: Path = Path(sys.argv[1])
    with redirect_stdout(sys.stderr):
        metrics: dict[str, float] | None = evaluate_compiler(compiler_filepath=compiler_filepath)
    if metrics is None:
        print("Public tests failed", file=sys.stderr)
        return 1
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

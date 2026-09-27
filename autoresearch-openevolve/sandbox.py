"""Run candidates under macOS sandbox-exec with a fixed restriction profile.

Starting from allow-default, the profile denies:
- file-write*: file creation, content/metadata changes, deletion, and renaming.
- network*: network operations.
- process-fork: creating child processes.
- signal: sending signals to other processes (macOS still permits self-signals).

Other operations, including reading host files and executing a program, remain
allowed. Children receive only the root PYTHONPATH and bytecode-disable setting,
not the parent's API credentials. Each command has a wall-clock timeout.
"""

from collections.abc import Sequence
from pathlib import Path
import subprocess
from typing import Final


PROFILE: Final[str] = (
    "(version 1)(allow default)(deny file-write*)(deny network*)"
    "(deny process-fork)(deny signal)"
)


def run_in_sandbox(command: Sequence[str], *, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    """Capture a command's output while enforcing PROFILE; run from the repo root."""
    return subprocess.run(
        ["/usr/bin/sandbox-exec", "-p", PROFILE, *command],
        env={"PYTHONPATH": str(Path.cwd()), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=timeout,
    )

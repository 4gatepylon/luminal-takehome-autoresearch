"""Create a shared .venv and install each repository requirement exactly once."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import venv
from glob import glob
from pathlib import Path


def find_requirements() -> list[Path]:
    # glob skips hidden directories, including .venv and run artifacts.
    requirements_paths = sorted(map(Path, glob("**/requirements.txt", recursive=True)), key=lambda path: (len(path.parts), str(path)))
    if not requirements_paths:
        raise ValueError("No requirements.txt files found; run from the repository root")
    if len({path.resolve() for path in requirements_paths}) != len(requirements_paths):
        raise ValueError("The same requirements file was discovered more than once")
    declarations: dict[str, str] = {}
    for requirements_path in requirements_paths:
        for line_number, line in enumerate(requirements_path.read_text().splitlines(), start=1):
            requirement = line.strip()
            if not requirement or requirement.startswith("#"):
                continue
            location = f"{requirements_path}:{line_number}"
            package_match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
            if package_match is None:
                raise ValueError(f"{location}: use a named requirement, not a pip option or file include")
            package_name = re.sub(r"[-_.]+", "-", package_match.group()).lower()
            if package_name in declarations:
                raise ValueError(f"Duplicate requirement {package_name}: {declarations[package_name]} and {location}")
            declarations[package_name] = location
    return requirements_paths


def main() -> None:
    requirements_paths = find_requirements()
    venv_python = Path(".venv/bin/python")
    if not venv_python.exists():
        if sys.version_info < (3, 10):  # noqa: UP036 - bootstrap must handle older Python versions.
            raise SystemExit("Python 3.10+ required; use make setup PYTHON=python3.13")
        venv.EnvBuilder(with_pip=True).create(".venv")
    subprocess.run(
        [str(venv_python), "-B", "-c", 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Existing .venv requires Python 3.10+")'],
        check=True,
    )
    pip_command = [str(venv_python), "-m", "pip"]
    subprocess.run([*pip_command, "install", "--upgrade", "pip"], check=True)
    for requirements_path in requirements_paths:
        subprocess.run([*pip_command, "install", "-r", str(requirements_path)], check=True)
    subprocess.run([*pip_command, "check"], check=True)

    env_path = Path("autoresearch-openevolve/.env")
    if not env_path.exists():
        shutil.copyfile(env_path.with_name(".env-example"), env_path)
    print("Setup complete. Configure autoresearch-openevolve/.env, then run make evolve.")


if __name__ == "__main__":
    main()

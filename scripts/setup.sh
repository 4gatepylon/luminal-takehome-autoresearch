#!/usr/bin/env bash
# Run from the repository root; share one environment across all requirements files.
set -euo pipefail

python_bin=${1:-python3}
venv_python=.venv/bin/python

if [[ ! -x "$venv_python" ]]; then
    "$python_bin" -B -c 'import sys; sys.exit("Python 3.10+ required; use make setup PYTHON=python3.13") if sys.version_info < (3, 10) else None'
    "$python_bin" -m venv .venv
fi
"$venv_python" -B -c 'import sys; sys.exit("Existing .venv requires Python 3.10+") if sys.version_info < (3, 10) else None'

"$venv_python" -m pip install --upgrade pip
"$venv_python" -m pip install -r requirements.txt
# Only repository requirements, excluding ignored virtualenvs and run artifacts.
while IFS= read -r -d '' requirements_path; do
    "$venv_python" -m pip install -r "$requirements_path"
done < <(git ls-files --cached --others --exclude-standard -z -- '*/requirements.txt')
"$venv_python" -m pip check

if [[ ! -e autoresearch-openevolve/.env ]]; then
    cp autoresearch-openevolve/.env-example autoresearch-openevolve/.env
fi
echo 'Setup complete. Configure autoresearch-openevolve/.env, then run make evolve.'

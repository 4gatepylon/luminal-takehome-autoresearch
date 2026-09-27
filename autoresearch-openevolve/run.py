#!/usr/bin/env python3
"""
- Input: work/compiler.py; OpenEvolve executes temporary copies under run-*/tmp/.
- Isolation: sandbox.py blocks candidate writes, networking, forks, and signals to
  other processes; see that module for the exact profile and its limitations.
- Model visibility:
  - Sees prompt.md rendered with the repo-root README.md and machine.py, current
    compiler code, sampled earlier candidates and metrics, and evaluation errors.
  - Full test/program files, evaluator source, .env, and other repository files
    are not automatically included in the prompt.
  - Has no direct shell or filesystem tools. Generated candidate code can still
    read host files, and returned error text can expose their contents.
- Install: Python 3.10+ on macOS; pip install -r autoresearch-openevolve/requirements.txt.
- Setup: copy .env-example to .env beside this script and configure the API.
- Run from the repo root: PYTHONPATH="$PWD" python -B autoresearch-openevolve/run.py.
  (-B: no bytecode caches.)
- --check: no API calls; run the shared eval(compiler_filepath=...) on work/compiler.py
  for public tests and scoring, with a 180-second timeout for the full evaluation.
- Outputs: the checkout stays unchanged; each run writes beneath this tree:

```
.autoresearch-openevolve/run-*/
├── tmp/          Temporary source/candidate files; cleaned up by OpenEvolve
├── logs/         Backend logs
├── database/     Candidate code, metrics, and prompts
├── artifacts/    Evaluation attachments, when produced
├── checkpoints/  Periodic snapshots, when due
└── best/         compiler.py plus OpenEvolve's best-program files and metadata
```
"""

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import shutil
from subprocess import CompletedProcess
import sys
import tempfile
from typing import Final

from dotenv import load_dotenv
from openevolve import run_evolution
from openevolve.api import EvolutionResult
from openevolve.config import Config, LLMConfig, LLMModelConfig
from openevolve.evaluation_result import EvaluationResult

from compatible_llm import CompatibleLLM
from evaluate import eval as evaluate_compiler
from sandbox import run_in_sandbox

REPO_ROOT: Final[Path] = Path.cwd()
COMPILER_PATH: Final[Path] = REPO_ROOT / "work/compiler.py"


def evaluate(candidate_path: str | Path) -> EvaluationResult:
    """Run the shared evaluation API in the sandbox and forward its metrics."""
    try:
        sandbox_result: CompletedProcess[str] = run_in_sandbox(
            [sys.executable, "-B", str(REPO_ROOT / "autoresearch-openevolve/run.py"),
             "--evaluate-candidate", str(Path(candidate_path).resolve())], timeout=180,
        )
        if sandbox_result.returncode:
            raise ValueError(sandbox_result.stderr[-4000:] or f"Evaluation exited with {sandbox_result.returncode}")
        metrics: dict[str, float] = json.loads(sandbox_result.stdout)
        return EvaluationResult(metrics=metrics)
    except Exception as exc:
        return EvaluationResult(metrics={"combined_score": 0.0},
                                artifacts={"error": str(exc)})


def init_config(run_dir: Path) -> Config:
    """Build OpenEvolve configuration from dotenv-loaded settings and prompt.md."""
    config = Config(max_iterations=int(os.getenv("ITERATIONS", "50")),
                    random_seed=None, log_dir=str(run_dir / "logs"))
    config.llm = LLMConfig(
        api_base=os.environ["OPENAI_BASE_URL"].rstrip("/"),
        api_key=os.environ["OPENAI_API_KEY"],
        models=[LLMModelConfig(name=os.environ["OPENAI_MODEL"], init_client=CompatibleLLM)],
        reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT") or None,
        max_tokens=int(os.environ["MAX_TOKENS"]) if os.getenv("MAX_TOKENS") else None,
        timeout=int(os.getenv("API_TIMEOUT", "180")),
    )
    config.database.db_path = str(run_dir / "database")
    config.database.artifacts_base_path = str(run_dir / "artifacts")
    config.evaluator.cascade_evaluation = False
    config.prompt.system_message = (REPO_ROOT / "autoresearch-openevolve/prompt.md").read_text().format(
        repo_root_readme=(REPO_ROOT / "README.md").read_text(),
        machine=(REPO_ROOT / "machine.py").read_text(),
    )
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--evaluate-candidate", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.evaluate_candidate:
        with redirect_stdout(sys.stderr):
            metrics: dict[str, float] | None = evaluate_compiler(compiler_filepath=args.evaluate_candidate)
        if metrics is None:
            print("Public tests failed", file=sys.stderr)
            return 1
        print(json.dumps(metrics))
        return 0
    if not shutil.which("sandbox-exec"):
        parser.error("macOS sandbox-exec is required; refusing to run candidates unsandboxed")
    if not COMPILER_PATH.is_file():
        parser.error("Expected work/compiler.py; run from the repository root")
    load_dotenv(REPO_ROOT / "autoresearch-openevolve/.env")
    if not args.check:
        for env_name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
            if not os.getenv(env_name):
                parser.error(f"Set {env_name} in autoresearch-openevolve/.env")

    output_dir: Path = REPO_ROOT / ".autoresearch-openevolve"
    output_dir.mkdir(exist_ok=True)
    run_dir: Path = Path(tempfile.mkdtemp(prefix="run-", dir=output_dir))
    (run_dir / "tmp").mkdir()
    os.environ["TMPDIR"] = tempfile.tempdir = str(run_dir / "tmp")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.check:
        evaluation_result: EvaluationResult = evaluate(COMPILER_PATH)
        print(json.dumps({"metrics": evaluation_result.metrics, "artifacts": evaluation_result.artifacts}, indent=2))
        return int(evaluation_result.metrics["combined_score"] <= 0)

    evolution_result: EvolutionResult = run_evolution(
        initial_program=COMPILER_PATH.read_text(), output_dir=str(run_dir),
        evaluator=str(REPO_ROOT / "autoresearch-openevolve/run.py"), config=init_config(run_dir),
    )
    if not evolution_result.best_code or evolution_result.best_score <= 0:
        raise RuntimeError(f"No correct compiler found; inspect {run_dir}")
    best_compiler_path: Path = run_dir / "best/compiler.py"
    best_compiler_path.parent.mkdir(exist_ok=True)
    best_compiler_path.write_text(evolution_result.best_code)
    print(f"Best score: {evolution_result.best_score:.6f}\nCompiler: {best_compiler_path}\nOutputs: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

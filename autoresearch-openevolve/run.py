#!/usr/bin/env python3
"""- Input: work/compiler.py; OpenEvolve executes temporary copies under run-*/tmp/.
- Isolation: sandbox.py blocks candidate writes, networking, forks, and signals to
  other processes; see that module for the exact profile and its limitations.
- Install: Python 3.10+ on macOS; pip install -r autoresearch-openevolve/requirements.txt.
- Setup: copy .env-example to .env beside this script and configure the API.
- Run from the repo root: PYTHONPATH="$PWD" python -B autoresearch-openevolve/run.py.
  (-B: no bytecode caches.)
- --check: no API calls; run work/compiler.py against every public program, validate
  its schedule and every case, and report cycle, scratch, and combined scores.
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
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

from dotenv import load_dotenv
from openevolve import run_evolution
from openevolve.config import Config, LLMConfig, LLMModelConfig
from openevolve.evaluation_result import EvaluationResult

import machine
from compatible_llm import CompatibleLLM
from sandbox import run_in_sandbox

REPO_ROOT = Path.cwd()
COMPILER_PATH = REPO_ROOT / "work/compiler.py"


def evaluate(candidate_path: str | Path) -> EvaluationResult:
    """Run candidate CLI in a read-only subprocess; grade JSON in trusted Python."""
    cycle_speedups, scratch_reductions = [], []
    try:
        program_paths = sorted((REPO_ROOT / "programs").glob("*.json"))
        if not program_paths:
            raise ValueError(f"No benchmark programs in {REPO_ROOT / 'programs'}")
        for program_path in program_paths:
            sandbox_result = run_in_sandbox(
                [sys.executable, "-B", str(Path(candidate_path).resolve()), str(program_path)],
            )
            if sandbox_result.returncode:
                raise ValueError(f"{program_path.name}: {sandbox_result.stderr[-4000:]}")
            compilation = json.loads(sandbox_result.stdout)
            program = machine.load_program(program_path)
            cycle_count = machine.check_compilation(program, compilation)
            for test_case in program["cases"]:
                machine.check_case(program, compilation, test_case)
            baseline_compilation = machine.serial_compile(program)
            cycle_speedups.append(machine.check_compilation(program, baseline_compilation) / cycle_count)
            scratch_reductions.append(machine.scratch_footprint(program, baseline_compilation)
                                      / machine.scratch_footprint(program, compilation))
        cycle_speedup_geomean = math.prod(cycle_speedups) ** (1 / len(cycle_speedups))
        scratch_reduction_geomean = math.prod(scratch_reductions) ** (1 / len(scratch_reductions))
        return EvaluationResult(metrics={
            "combined_score": math.sqrt(cycle_speedup_geomean * scratch_reduction_geomean),
            "cycle_speedup": cycle_speedup_geomean, "scratch_reduction": scratch_reduction_geomean,
        })
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
        readme=(REPO_ROOT / "README.md").read_text(),
        machine=(REPO_ROOT / "machine.py").read_text(),
    )
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not shutil.which("sandbox-exec"):
        parser.error("macOS sandbox-exec is required; refusing to run candidates unsandboxed")
    if not COMPILER_PATH.is_file():
        parser.error("Expected work/compiler.py; run from the repository root")
    load_dotenv(REPO_ROOT / "autoresearch-openevolve/.env")
    if not args.check:
        for env_name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
            if not os.getenv(env_name):
                parser.error(f"Set {env_name} in autoresearch-openevolve/.env")

    output_dir = REPO_ROOT / ".autoresearch-openevolve"
    output_dir.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=output_dir))
    (run_dir / "tmp").mkdir()
    os.environ["TMPDIR"] = tempfile.tempdir = str(run_dir / "tmp")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.check:
        evaluation_result = evaluate(COMPILER_PATH)
        print(json.dumps({"metrics": evaluation_result.metrics, "artifacts": evaluation_result.artifacts}, indent=2))
        return int(evaluation_result.metrics["combined_score"] <= 0)

    evolution_result = run_evolution(
        initial_program=COMPILER_PATH.read_text(), output_dir=str(run_dir),
        evaluator=str(REPO_ROOT / "autoresearch-openevolve/run.py"), config=init_config(run_dir),
    )
    if not evolution_result.best_code or evolution_result.best_score <= 0:
        raise RuntimeError(f"No correct compiler found; inspect {run_dir}")
    best_compiler_path = run_dir / "best/compiler.py"
    best_compiler_path.parent.mkdir(exist_ok=True)
    best_compiler_path.write_text(evolution_result.best_code)
    print(f"Best score: {evolution_result.best_score:.6f}\nCompiler: {best_compiler_path}\nOutputs: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

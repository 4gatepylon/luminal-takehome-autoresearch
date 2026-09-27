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

ROOT = Path.cwd()
COMPILER = ROOT / "work/compiler.py"


def evaluate(program_path):
    """Run candidate CLI in a read-only subprocess; grade JSON in trusted Python."""
    speedups, reductions = [], []
    try:
        paths = sorted((ROOT / "programs").glob("*.json"))
        if not paths:
            raise ValueError(f"No benchmark programs in {ROOT / 'programs'}")
        for path in paths:
            result = run_in_sandbox(
                [sys.executable, "-B", str(Path(program_path).resolve()), str(path)],
            )
            if result.returncode:
                raise ValueError(f"{path.name}: {result.stderr[-4000:]}")
            compilation = json.loads(result.stdout)
            program = machine.load_program(path)
            cycles = machine.check_compilation(program, compilation)
            for case in program["cases"]:
                machine.check_case(program, compilation, case)
            baseline = machine.serial_compile(program)
            speedups.append(machine.check_compilation(program, baseline) / cycles)
            reductions.append(machine.scratch_footprint(program, baseline)
                              / machine.scratch_footprint(program, compilation))
        speedup = math.prod(speedups) ** (1 / len(speedups))
        reduction = math.prod(reductions) ** (1 / len(reductions))
        return EvaluationResult(metrics={
            "combined_score": math.sqrt(speedup * reduction),
            "cycle_speedup": speedup, "scratch_reduction": reduction,
        })
    except Exception as exc:
        return EvaluationResult(metrics={"combined_score": 0.0},
                                artifacts={"error": str(exc)})


def init_config(run):
    """Build OpenEvolve configuration from dotenv-loaded settings and prompt.md."""
    config = Config(max_iterations=int(os.getenv("ITERATIONS", "50")),
                    random_seed=None, log_dir=str(run / "logs"))
    config.llm = LLMConfig(
        api_base=os.environ["OPENAI_BASE_URL"].rstrip("/"),
        api_key=os.environ["OPENAI_API_KEY"],
        models=[LLMModelConfig(name=os.environ["OPENAI_MODEL"], init_client=CompatibleLLM)],
        reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT") or None,
        max_tokens=int(os.environ["MAX_TOKENS"]) if os.getenv("MAX_TOKENS") else None,
        timeout=int(os.getenv("API_TIMEOUT", "180")),
    )
    config.database.db_path = str(run / "database")
    config.database.artifacts_base_path = str(run / "artifacts")
    config.evaluator.cascade_evaluation = False
    config.prompt.system_message = (ROOT / "autoresearch-openevolve/prompt.md").read_text().format(
        readme=(ROOT / "README.md").read_text(),
        machine=(ROOT / "machine.py").read_text(),
    )
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not shutil.which("sandbox-exec"):
        parser.error("macOS sandbox-exec is required; refusing to run candidates unsandboxed")
    if not COMPILER.is_file():
        parser.error("Expected work/compiler.py; run from the repository root")
    load_dotenv(ROOT / "autoresearch-openevolve/.env")
    if not args.check:
        for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
            if not os.getenv(name):
                parser.error(f"Set {name} in autoresearch-openevolve/.env")

    output = ROOT / ".autoresearch-openevolve"
    output.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    (run / "tmp").mkdir()
    os.environ["TMPDIR"] = tempfile.tempdir = str(run / "tmp")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.check:
        result = evaluate(COMPILER)
        print(json.dumps({"metrics": result.metrics, "artifacts": result.artifacts}, indent=2))
        return int(result.metrics["combined_score"] <= 0)

    result = run_evolution(
        initial_program=COMPILER.read_text(), output_dir=str(run),
        evaluator=str(ROOT / "autoresearch-openevolve/run.py"), config=init_config(run),
    )
    if not result.best_code or result.best_score <= 0:
        raise RuntimeError(f"No correct compiler found; inspect {run}")
    best = run / "best/compiler.py"
    best.parent.mkdir(exist_ok=True)
    best.write_text(result.best_code)
    print(f"Best score: {result.best_score:.6f}\nCompiler: {best}\nOutputs: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

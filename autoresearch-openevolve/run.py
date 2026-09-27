#!/usr/bin/env python3
"""Evolve only compiler.py; leave the checkout untouched (macOS sandbox-exec).

Python 3.10+: pip install -r autoresearch-openevolve/requirements.txt
Copy .env-example to .env beside this script, then: python autoresearch-openevolve/run.py
Use --check to evaluate the current compiler without making API calls.
Each run, including its best/compiler.py, lives in .autoresearch-openevolve/.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "work" if (ROOT / "work/compiler.py").is_file() else ROOT
SANDBOX = (
    "(version 1)(allow default)(deny file-write*)(deny network*)"
    "(deny process-fork)(deny signal)"
)


def init_client(model_config):
    """Add service-tier support and GPT-6 parameters to OpenEvolve 0.3.2."""
    from openevolve.llm.openai import OpenAILLM

    class CompatibleLLM(OpenAILLM):
        async def _call_api(self, params):
            if self.model.rsplit("/", 1)[-1].startswith("gpt-6"):
                params.pop("temperature", None)
                params.pop("top_p", None)
                params["max_completion_tokens"] = params.pop("max_tokens", None)
            for key in ("max_tokens", "max_completion_tokens"):
                if params.get(key) is None:
                    params.pop(key, None)
            if tier := os.getenv("OPENAI_SERVICE_TIER"):
                params["service_tier"] = tier
            return await super()._call_api(params)

    return CompatibleLLM(model_config)


def evaluate(program_path):
    """Run candidate CLI in a read-only subprocess; grade JSON in trusted Python."""
    from openevolve.evaluation_result import EvaluationResult

    spec = importlib.util.spec_from_file_location("reference_machine", SOURCE / "machine.py")
    machine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(machine)
    speedups, reductions = [], []
    try:
        paths = sorted((SOURCE / "programs").glob("*.json"))
        if not paths:
            raise ValueError(f"No benchmark programs in {SOURCE / 'programs'}")
        for path in paths:
            result = subprocess.run(
                ["/usr/bin/sandbox-exec", "-p", SANDBOX,
                 sys.executable, "-B", str(Path(program_path).resolve()), str(path)],
                cwd=Path(program_path).resolve().parent,
                env={"PYTHONPATH": str(SOURCE), "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True, text=True, timeout=20,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not shutil.which("sandbox-exec"):
        parser.error("macOS sandbox-exec is required; refusing to run candidates unsandboxed")

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
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
    os.chdir(run)

    if args.check:
        result = evaluate(SOURCE / "compiler.py")
        print(json.dumps({"metrics": result.metrics, "artifacts": result.artifacts}, indent=2))
        return int(result.metrics["combined_score"] <= 0)

    from openevolve import run_evolution
    from openevolve.config import Config, LLMConfig, LLMModelConfig

    config = Config(random_seed=None)  # Proxies need not support the optional seed field.
    config.llm = LLMConfig(
        api_base=os.environ["OPENAI_BASE_URL"].rstrip("/"),
        api_key=os.environ["OPENAI_API_KEY"],
        models=[LLMModelConfig(name=os.environ["OPENAI_MODEL"], init_client=init_client)],
        reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT") or None,
        max_tokens=int(os.environ["MAX_TOKENS"]) if os.getenv("MAX_TOKENS") else None,
        timeout=int(os.getenv("API_TIMEOUT", "180")),
    )
    config.log_dir = str(run / "logs")
    config.database.db_path = str(run / "database")
    config.database.artifacts_base_path = str(run / "artifacts")
    config.evaluator.cascade_evaluation = False
    config.evaluator.parallel_evaluations = 1
    config.evaluator.timeout = 300
    config.prompt.system_message = (
        "Optimize compiler.py's general VLIW scheduling and scratch allocation. "
        "Preserve compile_program(program) and the JSON-only CLI. Only this file evolves. "
        "Use standard-library imports and machine; no file writes, network, or subprocesses. "
        "Do not modify the input IR, monkeypatch machine, or special-case public programs. "
        "Maximize the combined score; every case must remain correct.\n\n"
        + (SOURCE / "README.md").read_text()
        + "\n\nRead-only machine.py:\n" + (SOURCE / "machine.py").read_text()
    )
    result = run_evolution(
        initial_program=(SOURCE / "compiler.py").read_text(),
        evaluator=str(Path(__file__).resolve()), config=config,
        iterations=int(os.getenv("ITERATIONS", "50")), output_dir=str(run),
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

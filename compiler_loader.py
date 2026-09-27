"""Load a compiler's compile_program function from a Python file."""

from pathlib import Path
from runpy import run_path

DEFAULT_COMPILER_PATH = Path(__file__).parent / "work" / "compiler.py"


def load_compiler(compiler_path: str | Path = DEFAULT_COMPILER_PATH):
    compile_fn = run_path(str(compiler_path)).get("compile_program")
    if not callable(compile_fn):
        raise TypeError(f"{compiler_path} must define a callable compile_program(program)")
    return compile_fn

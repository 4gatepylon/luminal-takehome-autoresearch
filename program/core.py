"""The existing program dictionary and its shared validation contract.

Validation remains owned by machine until the later migration; reuse it here
so the new representations cannot diverge from the compiler's input format.
"""

from typing import Any, TypeAlias

from machine import ProgramError, validate_program


Program: TypeAlias = dict[str, Any]

__all__ = ["Program", "ProgramError", "validate_program"]

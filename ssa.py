#!/usr/bin/env python3
"""Convert machine program dictionaries to and from a line-oriented SSA language."""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
from pathlib import Path

import machine


IDENTIFIER = r"[A-Za-z_][A-Za-z_0-9]*"
NAME = IDENTIFIER
INTEGER = r"-?(?:0[xX][0-9a-fA-F]+|[0-9]+)"
BINARY = {
    "+": "add", "-": "sub", "*": "mul", "^": "xor", "&": "and",
    "|": "or", "<<": "shl", ">>": "shr", "==": "eq", "<": "lt",
}
SYMBOLS = {opcode: symbol for symbol, opcode in BINARY.items()}
SECTIONS = tuple("=" * 40 + title + "=" * 40 for title in ("BUFFERS", "PROGRAM", "CASES"))


def _name(text: str) -> str:
    if not re.fullmatch(IDENTIFIER, text) or keyword.iskeyword(text):
        raise machine.ProgramError(f"invalid identifier {text!r}")
    return text


def _integer(text: str) -> int:
    return int(text, 16 if "x" in text.lower() else 10)


def to_ssa(program: dict) -> str:
    """Serialize a validated program's documented fields; IDs follow source order."""
    machine.validate_program(program)
    for name in program["buffers"]:
        _name(name)
    lines = [SECTIONS[0], f"name {json.dumps(program['name'])}",
             f"buffers {json.dumps(program['buffers'])}", "", SECTIONS[1]]
    for operation in program["operations"]:
        opcode = operation["op"]
        args = [_name(arg) for arg in operation.get("args", [])]
        dest = _name(operation["dest"]) if "dest" in operation else None
        if opcode in machine.MEMORY_OPS:
            address = f"buff[{_name(operation['buffer'])}][{operation['offset']}]"
            if opcode in machine.LOAD_OPS:
                line = f"{opcode} {{{address}}} into {{{dest}}}"
            else:
                line = f"{opcode} {{{args[0]}}} into {{{address}}}"
        elif opcode == "const":
            line = f"{dest} = {operation['value']}"
        elif opcode in {"select", "vselect"}:
            line = f"{dest} = {args[1]} if {{{args[0]}}} else {args[2]}"
        elif opcode == "splat":
            line = f"{dest} = {opcode}({', '.join(args)})"
        else:
            scalar_opcode = opcode[1:] if opcode.startswith("v") else opcode
            line = f"{dest} = {args[0]} {SYMBOLS[scalar_opcode]} {args[1]}"
        lines.append(line)
    lines.extend(["", SECTIONS[2]])
    lines.extend(json.dumps(case) for case in program["cases"])
    return "\n".join(lines) + "\n"


def _parse_operation(line: str, kinds: dict[str, str]) -> dict:
    address = rf"\{{\s*buff\s*\[\s*({NAME})\s*\]\s*\[\s*({INTEGER})\s*\]\s*\}}"
    variable = rf"\{{\s*({NAME})\s*\}}"
    match = re.fullmatch(rf"(v?load)\s+{address}\s+into\s+{variable}", line)
    if match:
        opcode, buffer, offset, dest = match.groups()
        return {"op": opcode, "dest": _name(dest), "buffer": _name(buffer),
                "offset": _integer(offset)}
    match = re.fullmatch(rf"(v?store)\s+{variable}\s+into\s+{address}", line)
    if match:
        opcode, arg, buffer, offset = match.groups()
        return {"op": opcode, "args": [_name(arg)], "buffer": _name(buffer),
                "offset": _integer(offset)}
    match = re.fullmatch(rf"({NAME})\s*=\s*(.+)", line)
    if not match:
        raise machine.ProgramError("expected a load, store, or SSA assignment")
    dest, expression = match.groups()
    operation = {"dest": _name(dest)}
    if re.fullmatch(INTEGER, expression):
        return {**operation, "op": "const", "value": _integer(expression)}
    match = re.fullmatch(rf"splat\(\s*({NAME})\s*\)", expression)
    if match:
        return {**operation, "op": "splat", "args": [_name(match[1])]}
    match = re.fullmatch(
        rf"({NAME})\s+if\s+{variable}\s+else\s+({NAME})", expression
    )
    if match:
        true_value, condition, false_value = [_name(v) for v in match.groups()]
        opcode = "vselect" if kinds.get(condition) == "vector" else "select"
        return {**operation, "op": opcode, "args": [condition, true_value, false_value]}
    operators = "|".join(re.escape(symbol) for symbol in BINARY)
    match = re.fullmatch(rf"({NAME})\s*({operators})\s*({NAME})", expression)
    if match:
        left, symbol, right = match.groups()
        args = [_name(left), _name(right)]
        opcode = BINARY[symbol]
        if kinds.get(args[0]) == "vector":
            opcode = "v" + opcode
        if opcode not in machine.OP_SPECS:
            raise machine.ProgramError(f"operator {symbol!r} does not support vectors")
        return {**operation, "op": opcode, "args": args}
    raise machine.ProgramError("invalid expression (inline comments are not supported)")


def from_ssa(source: str) -> dict:
    """Parse SSA text into a validated machine program dictionary.

    Blank lines and full-line # comments are ignored. Each instruction defines
    exactly one original operation. Infix vector operations are inferred from
    their operands; the machine validator enforces SSA definitions and types.
    """
    program = {"operations": [], "cases": []}
    kinds: dict[str, str] = {}
    section = -1
    for line_number, raw_line in enumerate(source.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            if line in SECTIONS:
                if section + 1 >= len(SECTIONS) or line != SECTIONS[section + 1]:
                    raise machine.ProgramError("expected sections BUFFERS, PROGRAM, CASES in order")
                section += 1
                continue
            if section == -1:
                raise machine.ProgramError("expected BUFFERS section header")
            if section == 2:
                program["cases"].append(json.loads(line))
                continue
            if section == 0:
                directive = re.fullmatch(r"(name|buffers)\s+(.+)", line)
                if not directive:
                    raise machine.ProgramError("expected name or buffers declaration")
                keyword, value = directive.groups()
                value = json.loads(value)
                if keyword in program:
                    raise machine.ProgramError(f"duplicate {keyword} declaration")
                program[keyword] = value
                continue
            operation = _parse_operation(line, kinds)
            operation["id"] = len(program["operations"])
            program["operations"].append(operation)
            if "dest" in operation:
                kinds[operation["dest"]] = machine.OP_SPECS[operation["op"]]["result"]
        except (ValueError, TypeError) as exc:
            raise machine.ProgramError(f"line {line_number}: {exc}") from exc
    if section != 2:
        raise machine.ProgramError("expected all three sections: BUFFERS, PROGRAM, CASES")
    machine.validate_program(program)
    for name in program["buffers"]:
        _name(name)
    return program


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=("to-ssa", "to-json"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        if args.direction == "to-ssa":
            sys.stdout.write(to_ssa(machine.load_program(args.path)))
        else:
            program = from_ssa(args.path.read_text(encoding="utf-8"))
            print(json.dumps(program, indent=2))
    except (OSError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

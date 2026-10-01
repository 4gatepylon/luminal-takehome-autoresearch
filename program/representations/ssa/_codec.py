"""Lossless JSON <-> ssa-v1 codec; this module never executes a program."""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
from pathlib import Path

import machine

SECTIONS = tuple(f"================ {name} ================" for name in ("BUFFERS", "PROGRAM", "CASES"))
OPERATORS = {
    "+": "add",
    "-": "sub",
    "*": "mul",
    "^": "xor",
    "&": "and",
    "|": "or",
    "<<": "shl",
    ">>": "shr",
    "==": "eq",
    "<": "lt",
}
SYMBOLS = {opcode: symbol for symbol, opcode in OPERATORS.items()}
RESERVED = {"buff", "const"}
TOKEN = re.compile(r"\.\.\.|<<|>>|==|[=+\-\*^&|<>\[\]{}():,@.]|[^\s=+\-\*^&|<>\[\]{}():,@.]+")
SPACE = re.compile(r"\s*")


class SSAError(ValueError):
    """Invalid source, with source-line context where available."""


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SSAError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise SSAError(f"{value} is not a JSON value")


DECODER = json.JSONDecoder(object_pairs_hook=_object, parse_constant=_invalid_constant)


def _json(text: str, line: int) -> object:
    try:
        return DECODER.decode(text)
    except ValueError as error:
        raise SSAError(f"line {line}: {error}") from error


def _dump(value: object) -> str:
    text = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    for marker in SECTIONS:
        text = text.replace(marker, marker.replace("=", r"\u003d"))
    return text


def _identifier(name: object) -> bool:
    return isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name) and name not in RESERVED


def _aliases(names: list[str], prefix: str) -> tuple[dict[str, str], dict[str, str]]:
    used = {name for name in names if _identifier(name)}
    forward, reverse = {}, {}
    for name in names:
        alias = name
        if not _identifier(name):
            index = len(reverse)
            alias = f"{prefix}_{index}"
            while alias in used:
                index += 1
                alias = f"{prefix}_{index}"
            used.add(alias)
            reverse[alias] = name
        forward[name] = alias
    return forward, reverse


def _memory(operation: dict, buffers: dict[str, str]) -> str:
    start = operation["offset"]
    index = f"{start}:{start + machine.VLEN}" if operation["op"].startswith("v") else str(start)
    return f"buff[{buffers[operation['buffer']]}][{index}]"


def format_program(program: dict) -> str:
    """Encode a valid program without mutating it or dropping extra fields."""
    machine.validate_program(program)
    buffers, buffer_aliases = _aliases(list(program["buffers"]), "buffer")
    values, value_aliases = _aliases([op["dest"] for op in program["operations"] if "dest" in op], "value")
    lines = ["lang: ssa-v1", f"name: {_dump(program['name'])}"]
    aliases = {key: value for key, value in (("buffers", buffer_aliases), ("values", value_aliases)) if value}
    if aliases:
        lines.append(f"aliases: {_dump(aliases)}")
    metadata = {key: value for key, value in program.items() if key not in {"name", "buffers", "operations", "cases"}}
    if metadata:
        lines.append(f"metadata: {_dump(metadata)}")
    lines.extend(["", SECTIONS[0]])
    lines.extend(_dump({buffers[name]: length}) for name, length in program["buffers"].items())
    lines.extend(["", SECTIONS[1]])
    for operation in program["operations"]:
        opcode = operation["op"]
        args = [values[name] for name in operation.get("args", [])]
        consumed = {"id", "op"}
        if args:
            consumed.add("args")
        if opcode in machine.STORE_OPS:
            statement = f"{_memory(operation, buffers)} = {args[0]}"
            consumed.update(("buffer", "offset"))
        else:
            consumed.add("dest")
            if opcode == "const":
                expression = f"const({operation['value']})"
                consumed.add("value")
            elif opcode in machine.LOAD_OPS:
                expression = _memory(operation, buffers)
                consumed.update(("buffer", "offset"))
            elif opcode == "splat":
                expression = f"...{args[0]}"
            elif opcode in {"select", "vselect"}:
                expression = f"{args[1]} if {{ {args[0]} }} else {args[2]}"
            else:
                scalar_opcode = opcode.removeprefix("v")
                expression = f"{args[0]} {SYMBOLS[scalar_opcode]} {args[1]}"
            statement = f"{values[operation['dest']]} = {expression}"
        extra = {key: value for key, value in operation.items() if key not in consumed}
        if extra:
            statement += f" @ {_dump(extra)}"
        lines.append(statement)
    lines.extend(["", SECTIONS[2]])
    lines.extend(_dump(case) for case in program["cases"])
    return "\n".join(lines) + "\n"


class _Parser:
    """A fixed-arity statement grammar; newlines have no grammatical role."""

    def __init__(self, source: str, buffers: dict):
        self.source = source
        self.position = 0
        self.buffers = buffers
        self.definitions: dict[str, str] = {}
        self.operations: list[dict] = []

    def line(self) -> int:
        return self.source.count("\n", 0, self.position) + 1

    def fail(self, message: str) -> None:
        raise SSAError(f"line {self.line()}: {message}")

    def peek(self) -> str:
        self.position = SPACE.match(self.source, self.position).end()
        match = TOKEN.match(self.source, self.position)
        return match.group() if match else ""

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if not token or (expected is not None and token != expected):
            self.fail(f"expected {expected or 'token'!r}, found {token or 'end of program'!r}")
        self.position += len(token)
        return token

    def name(self) -> str:
        if not _identifier(self.peek()):
            self.fail(f"expected a Python identifier, found {self.peek()!r}")
        return self.take()

    def value(self) -> str:
        self.peek()
        line = self.line()
        name = self.name()
        if name not in self.definitions:
            raise SSAError(f"line {line}: undefined value {name!r}")
        return name

    def integer(self) -> int:
        sign = 1
        if self.peek() == "-":
            self.take("-")
            sign = -1
        token = self.peek()
        if not re.fullmatch(r"[0-9]+", token):
            self.fail(f"expected an integer, found {token!r}")
        return sign * int(self.take())

    def memory(self) -> tuple[dict, str]:
        self.take("buff")
        self.take("[")
        buffer = self.name()
        if buffer not in self.buffers:
            self.fail(f"unknown buffer {buffer!r}")
        self.take("]")
        self.take("[")
        start = self.integer()
        kind = "scalar"
        if self.peek() == ":":
            self.take(":")
            end = self.integer()
            if end - start != machine.VLEN:
                self.fail(f"vector access must span exactly {machine.VLEN} words")
            kind = "vector"
        self.take("]")
        width = machine.VLEN if kind == "vector" else 1
        if start < 0 or start + width > self.buffers[buffer]:
            self.fail(f"memory access outside buffer {buffer!r}")
        return {"buffer": buffer, "offset": start}, kind

    def expression(self) -> dict:
        token = self.peek()
        if token == "const":
            self.take()
            self.take("(")
            value = self.integer()
            self.take(")")
            return {"op": "const", "value": value}
        if token == "buff":
            fields, kind = self.memory()
            return {"op": "vload" if kind == "vector" else "load", **fields}
        if token == "...":
            self.take()
            return {"op": "splat", "args": [self.value()]}
        first = self.value()
        if self.peek() == "if":
            self.take()
            self.take("{")
            condition = self.value()
            self.take("}")
            self.take("else")
            other = self.value()
            opcode = "vselect" if self.definitions[condition] == "vector" else "select"
            return {"op": opcode, "args": [condition, first, other]}
        symbol = self.peek()
        if symbol not in OPERATORS:
            self.fail(f"expected a binary operator or 'if', found {symbol!r}")
        self.take()
        opcode = OPERATORS[symbol]
        if self.definitions[first] == "vector":
            opcode = "v" + opcode
        if opcode not in machine.OP_SPECS:
            self.fail(f"operator {symbol!r} does not support vectors")
        return {"op": opcode, "args": [first, self.value()]}

    def parse(self) -> list[dict]:
        while self.peek():
            line = self.line()
            if self.peek() == "buff":
                fields, kind = self.memory()
                self.take("=")
                operation = {"op": "vstore" if kind == "vector" else "store", "args": [self.value()], **fields}
            else:
                dest = self.name()
                if dest in self.definitions:
                    self.fail(f"duplicate definition {dest!r}")
                self.take("=")
                operation = {"dest": dest, **self.expression()}
            operation["id"] = len(self.operations)
            if self.peek() == "@":
                self.take()
                self.position = SPACE.match(self.source, self.position).end()
                try:
                    extra, end = DECODER.raw_decode(self.source, self.position)
                except ValueError as error:
                    self.fail(f"invalid operation metadata: {error}")
                self.position = end
                _merge(operation, extra, line)
            spec = machine.OP_SPECS[operation["op"]]
            args = operation.get("args", [])
            if not isinstance(args, list) or len(args) != len(spec["args"]):
                self.fail(f"{operation['op']} expects {len(spec['args'])} arguments")
            for arg, kind in zip(args, spec["args"]):
                if self.definitions.get(arg) != kind:
                    raise SSAError(f"line {line}: operation {operation['id']} ({operation['op']}) expects {kind} operand {arg!r}")
            if spec["result"]:
                self.definitions[operation["dest"]] = spec["result"]
            self.operations.append(operation)
        return self.operations


def _merge(target: dict, extra: object, line: int) -> None:
    if not isinstance(extra, dict):
        raise SSAError(f"line {line}: metadata must be a JSON object")
    overlap = target.keys() & extra.keys()
    if overlap:
        raise SSAError(f"line {line}: metadata cannot override {sorted(overlap)!r}")
    target.update(extra)


def _sections(source: str) -> tuple[list[tuple[int, str]], dict[str, list[tuple[int, str]]]]:
    header: list[tuple[int, str]] = []
    sections: dict[str, list[tuple[int, str]]] = {}
    current = header
    for line_number, raw in enumerate(source.split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in SECTIONS:
            if len(sections) == len(SECTIONS) or line != SECTIONS[len(sections)]:
                raise SSAError(f"line {line_number}: duplicate or out-of-order section marker")
            current = []
            sections[line] = current
        else:
            if any(marker in raw for marker in SECTIONS):
                raise SSAError(f"line {line_number}: reserved section marker in data; escape '=' as \\u003d")
            current.append((line_number, raw))
    if len(sections) != len(SECTIONS):
        raise SSAError(f"missing section marker: {SECTIONS[len(sections)]}")
    return header, sections


def _restore_names(program: dict, aliases: object) -> None:
    if not isinstance(aliases, dict) or aliases.keys() - {"buffers", "values"}:
        raise SSAError("aliases must contain only 'buffers' and/or 'values' objects")
    for namespace in ("buffers", "values"):
        mapping = aliases.get(namespace, {})
        names = (
            list(program["buffers"])
            if namespace == "buffers"
            else [op["dest"] for op in program["operations"] if machine.OP_SPECS[op["op"]]["result"]]
        )
        if not isinstance(mapping, dict) or any(not _identifier(alias) or not isinstance(name, str) or not name for alias, name in mapping.items()):
            raise SSAError(f"invalid {namespace} aliases")
        if mapping.keys() - set(names):
            raise SSAError(f"unused {namespace} alias")
        restored = [mapping.get(name, name) for name in names]
        if len(set(restored)) != len(restored):
            raise SSAError(f"colliding {namespace} aliases")
    buffers, values = aliases.get("buffers", {}), aliases.get("values", {})
    program["buffers"] = {buffers.get(name, name): size for name, size in program["buffers"].items()}
    for operation in program["operations"]:
        spec = machine.OP_SPECS[operation["op"]]
        if spec["result"]:
            operation["dest"] = values.get(operation["dest"], operation["dest"])
        if spec["args"]:
            operation["args"] = [values.get(name, name) for name in operation["args"]]
        if operation["op"] in machine.MEMORY_OPS:
            operation["buffer"] = buffers.get(operation["buffer"], operation["buffer"])


def parse_program(source: str) -> dict:
    """Decode ssa-v1, restore original names/metadata, and validate the program."""
    header, sections = _sections(source)
    if not header or header[0][1].strip() != "lang: ssa-v1":
        raise SSAError("expected 'lang: ssa-v1' as the first non-comment line")
    fields = {}
    for line, text in header[1:]:
        key, separator, value = text.strip().partition(":")
        if not separator or key not in {"name", "metadata", "aliases"} or key in fields:
            raise SSAError(f"line {line}: unknown or duplicate header {key!r}")
        fields[key] = _json(value.strip(), line)
    if not isinstance(fields.get("name"), str) or not fields["name"]:
        raise SSAError("header requires a non-empty JSON string 'name'")
    buffers = {}
    for line, text in sections[SECTIONS[0]]:
        entry = _json(text, line)
        if not isinstance(entry, dict) or len(entry) != 1:
            raise SSAError(f'line {line}: expected one buffer declaration, e.g. {{"a":8}}')
        name, size = next(iter(entry.items()))
        if not _identifier(name) or name in buffers:
            raise SSAError(f"line {line}: invalid or duplicate buffer name {name!r}")
        if type(size) is not int or size <= 0:
            raise SSAError(f"line {line}: buffer length must be a positive integer")
        buffers[name] = size
    # Keep physical line positions, including blank/comment lines, for diagnostics.
    program_lines = [""] * len(source.split("\n"))
    for line, text in sections[SECTIONS[1]]:
        program_lines[line - 1] = text
    parser = _Parser("\n".join(program_lines), buffers)
    program = {"name": fields["name"], "buffers": buffers, "operations": parser.parse(), "cases": []}
    _merge(program, fields.get("metadata", {}), header[0][0])
    _restore_names(program, fields.get("aliases", {}))
    for line, text in sections[SECTIONS[2]]:
        case = _json(text, line)
        try:
            machine.validate_case(program, case, len(program["cases"]))
        except machine.ProgramError as error:
            raise SSAError(f"line {line}: {error}") from error
        program["cases"].append(case)
    try:
        machine.validate_program(program)
    except machine.ProgramError as error:
        raise SSAError(str(error)) from error
    return program


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("to-ssa", "to-json"))
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="output file (default: stdout); SSA files must end in .ssa")
    args = parser.parse_args(argv)
    try:
        if args.command == "to-ssa" and args.output and args.output.suffix != ".ssa":
            raise SSAError("SSA output files must end in .ssa")
        if args.command == "to-json" and args.input.suffix != ".ssa":
            raise SSAError("SSA input files must end in .ssa")
        source = args.input.read_text(encoding="utf-8")
        if args.command == "to-ssa":
            output = format_program(_json(source, 1))
        else:
            output = json.dumps(parse_program(source), ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"{args.input}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

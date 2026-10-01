#!/usr/bin/env python3
"""Render a program's SSA values and operation junctions as a Graphviz SVG."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lib.dag import topological_layers
from machine import OP_SPECS, ProgramError, load_program, memory_width, producer_map


SYMBOLS = {
    "add": "+", "sub": "−", "mul": "×", "xor": "⊕", "and": "&",
    "or": "|", "shl": "≪", "shr": "≫", "eq": "=", "lt": "<",
    "select": "select", "splat": "splat",
}
COLORS = {"scalar": "#dbeafe", "vector": "#dcfce7"}


def quote(text: str) -> str:
    """Quote literal DOT strings, including backslashes in SSA names."""
    return json.dumps(text, ensure_ascii=False)


def memory_label(operation: dict) -> str:
    start = operation["offset"]
    width = memory_width(operation)
    index = str(start) if width == 1 else f"{start}:{start + width}"
    return f"{operation['buffer']}[{index}]"


def program_dot(program: dict) -> str:
    """Build a value graph from validated IR; no program code is executed.

    Each SSA value is a box; operation nodes sit just above their results.
    Stores are sinks. Layers describe dataflow only, not memory ordering or
    scheduled cycles. IDs derive from operation IDs, never user-provided names.
    """
    operations = program["operations"]
    producers = producer_map(program)
    dependencies = [
        (producers[arg], operation["id"])
        for operation in operations
        for arg in operation.get("args", [])
    ]
    layers = topological_layers([op["id"] for op in operations], dependencies)
    lines = [
        "digraph SSA {",
        '  graph [rankdir=TB, bgcolor="white", pad=0.35, nodesep=0.4,',
        '         ranksep="0.5 equally", splines=true, fontname="Helvetica",',
        f'         labelloc=t, fontsize=18, label={quote(program["name"] + chr(10) + "SSA dataflow · blue: scalar · green: vector · orange: memory" + chr(10) + "Layers show dependency depth, not cycles; memory ordering omitted")}];',
        '  node [fontname="Helvetica", fontsize=12, color="#64748b", penwidth=1.2];',
        '  edge [color="#64748b", arrowsize=0.65, fontname="Helvetica", fontsize=9];',
    ]
    for operation in operations:
        op_id = operation["id"]
        opcode = operation["op"]
        kind = OP_SPECS[opcode]["result"]
        tooltip = f"#{op_id} {opcode} · latency {OP_SPECS[opcode]['latency']}"
        if opcode == "const":
            label = f"const {operation['value']}"
        elif "buffer" in operation:
            label = f"{opcode} {memory_label(operation)}"
        else:
            scalar_opcode = opcode[1:] if opcode.startswith("v") else opcode
            label = SYMBOLS.get(scalar_opcode, opcode)
        memory = "buffer" in operation
        lines.append(
            f"  op{op_id} [label={quote(label)}, tooltip={quote(tooltip)}, "
            f'shape={"box" if memory or opcode == "const" else "ellipse"}, '
            f'style="filled,rounded", fillcolor="{"#ffedd5" if memory else "#f1f5f9"}"];'
        )
        if kind is not None:
            label = f"{operation['dest']}\n{'u32 × 8' if kind == 'vector' else 'u32'}"
            lines.append(
                f"  v{op_id} [label={quote(label)}, shape=box, "
                f'style="filled,rounded", fillcolor="{COLORS[kind]}"];'
            )
            lines.append(f"  op{op_id} -> v{op_id};")
        for index, arg in enumerate(operation.get("args", [])):
            # Keep repeated operands as distinct edges; order matters for select/sub.
            lines.append(
                f"  v{producers[arg]} -> op{op_id} "
                f'[headlabel="{index + 1}", tooltip={quote(arg + " (operand " + str(index + 1) + ")")}];'
            )

    for layer in layers:
        lines.append("  { rank=same; " + "; ".join(f"op{i}" for i in layer) + "; }")
        values = [f"v{i}" for i in layer if "dest" in operations[i]]
        if values:
            lines.append("  { rank=same; " + "; ".join(values) + "; }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path, help="program JSON in this repository's SSA format")
    parser.add_argument("-o", "--output", type=Path, help="output .svg or .dot (default: <program>.svg)")
    args = parser.parse_args()
    output = args.output or args.program.with_suffix(".svg")
    if output.suffix.lower() not in {".svg", ".dot"}:
        parser.error("output must have an .svg or .dot extension")
    dot_path = output.with_suffix(".dot")
    if args.program.resolve() in {output.resolve(), dot_path.resolve()}:
        parser.error("output must not overwrite the input program")
    try:
        source = program_dot(load_program(args.program))
        if output.suffix.lower() == ".svg":
            dot = shutil.which("dot")
            if dot is None:
                raise ValueError("Graphviz is required: brew install graphviz (or use -o graph.dot)")
            rendered = subprocess.run(
                [dot, "-Tsvg"], input=source, text=True, capture_output=True,
                check=True, timeout=30,
            ).stdout
            output.write_text(rendered, encoding="utf-8")
        dot_path.write_text(source, encoding="utf-8")
    except (OSError, ValueError, ProgramError, subprocess.SubprocessError) as exc:
        print(f"visualize_ssa: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {output}" + (f" and {dot_path}" if output != dot_path else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

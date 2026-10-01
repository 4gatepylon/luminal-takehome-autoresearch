"""Build DOT diagrams from validated SSA programs."""

import json

from machine import OP_SPECS, memory_width, producer_map
from visualize_ssa_as_dag._topology import topological_layers


_SYMBOLS = {
    "add": "+", "sub": "−", "mul": "×", "xor": "⊕", "and": "&",
    "or": "|", "shl": "≪", "shr": "≫", "eq": "=", "lt": "<",
    "select": "select", "splat": "splat",
}
_COLORS = {"scalar": "#dbeafe", "vector": "#dcfce7"}


def _quote(text: str) -> str:
    """Quote literal DOT strings, including backslashes in SSA names."""
    return json.dumps(text, ensure_ascii=False)


def _memory_label(operation: dict) -> str:
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
    title = (
        f"{program['name']}\n"
        "SSA dataflow · blue: scalar · green: vector · orange: memory\n"
        "Layers show dependency depth, not cycles; memory ordering omitted"
    )
    # Bound layout optimization so wide reduction graphs render promptly.
    lines = [
        "digraph SSA {",
        '  graph [rankdir=TB, bgcolor="white", pad=0.35, nodesep=0.4,',
        '         nslimit=2, nslimit1=2,',
        '         ranksep="0.5 equally", splines=true, fontname="Helvetica",',
        f"         labelloc=t, fontsize=18, label={_quote(title)}];",
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
            label = f"{opcode} {_memory_label(operation)}"
        else:
            scalar_opcode = opcode[1:] if opcode.startswith("v") else opcode
            label = _SYMBOLS.get(scalar_opcode, opcode)
        memory = "buffer" in operation
        lines.append(
            f"  op{op_id} [label={_quote(label)}, tooltip={_quote(tooltip)}, "
            f'shape={"box" if memory or opcode == "const" else "ellipse"}, '
            f'style="filled,rounded", fillcolor="{"#ffedd5" if memory else "#f1f5f9"}"];'
        )
        if kind is not None:
            label = f"{operation['dest']}\n{'u32 × 8' if kind == 'vector' else 'u32'}"
            lines.append(
                f"  v{op_id} [label={_quote(label)}, shape=box, "
                f'style="filled,rounded", fillcolor="{_COLORS[kind]}"];'
            )
            lines.append(f"  op{op_id} -> v{op_id};")
        for index, arg in enumerate(operation.get("args", [])):
            # Keep repeated operands as distinct edges; order matters for select/sub.
            tooltip = _quote(f"{arg} (operand {index + 1})")
            lines.append(
                f"  v{producers[arg]} -> op{op_id} "
                f'[headlabel="{index + 1}", tooltip={tooltip}];'
            )

    for layer in layers:
        lines.append("  { rank=same; " + "; ".join(f"op{i}" for i in layer) + "; }")
        values = [f"v{i}" for i in layer if "dest" in operations[i]]
        if values:
            lines.append("  { rank=same; " + "; ".join(values) + "; }")
    lines.append("}")
    return "\n".join(lines) + "\n"

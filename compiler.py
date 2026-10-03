#!/usr/bin/env python3
"""Luminal Compiler Take Home — compiler engineering candidate implementation.

The compiler allocates every SSA value once and greedily packs operations into
bundles in source order. Improve compile_program without
changing its input or output contract. Reuse scratch for values whose scheduled
lifetimes do not overlap to improve the scratch-footprint component of the score.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import ClassVar

import machine


@dataclass(eq=False, kw_only=True)
class Node:
    """A graph vertex, with identity-based equality and bidirectional edges.

    Adjacency maps associate neighboring nodes with their minimum issue-cycle
    separation. Links are excluded from repr to avoid recursively printing the
    graph. Operand order and repeated operands live in OperationNode.args.
    """

    predecessors: dict[Node, int] = field(default_factory=dict, init=False, repr=False)
    successors: dict[Node, int] = field(default_factory=dict, init=False, repr=False)


@dataclass(eq=False, kw_only=True)
class InitialStoreNode(Node):
    """The entire buffer's initial contents, available before any instruction.

    This synthetic store has version zero, no predecessors, and no instruction
    ID. Its contents come from the execution's input case, not from a constant
    captured during graph construction.
    """

    buffer: str
    width: int
    offset: int = field(default=0, init=False)
    version: int = field(default=0, init=False)
    latency: int = field(default=0, init=False)

    @property
    def address_range(self) -> tuple[int, int]:
        """Word addresses as a half-open (start, end) interval."""
        return (self.offset, self.offset + self.width)


@dataclass(eq=False, kw_only=True)
class OperationNode(Node):
    """One original SSA operation; concrete subclasses fix its opcode."""

    id: int
    dest: str | None = None
    args: tuple[str, ...] = ()
    op: ClassVar[str]

    @property
    def engine(self) -> str:
        return machine.OP_SPECS[self.op]["engine"]

    @property
    def latency(self) -> int:
        return machine.OP_SPECS[self.op]["latency"]

    @property
    def result_kind(self) -> str | None:
        return machine.OP_SPECS[self.op]["result"]


@dataclass(eq=False, kw_only=True)
class MemoryNode(OperationNode):
    """A memory access and its buffer version in original program order.

    Loads read the current version. Stores create the next version, even when
    they only update part of a buffer. The offset remains a word address.
    """

    buffer: str
    offset: int
    width: int
    version: int

    @property
    def address_range(self) -> tuple[int, int]:
        """Word addresses as a half-open (start, end) interval."""
        return (self.offset, self.offset + self.width)


@dataclass(eq=False, kw_only=True)
class ConstNode(OperationNode):
    op: ClassVar[str] = "const"
    value: int


@dataclass(eq=False, kw_only=True)
class LoadNode(MemoryNode):
    op: ClassVar[str] = "load"


@dataclass(eq=False, kw_only=True)
class VLoadNode(MemoryNode):
    op: ClassVar[str] = "vload"


@dataclass(eq=False, kw_only=True)
class StoreNode(MemoryNode):
    op: ClassVar[str] = "store"


@dataclass(eq=False, kw_only=True)
class VStoreNode(MemoryNode):
    op: ClassVar[str] = "vstore"


@dataclass(eq=False, kw_only=True)
class AddNode(OperationNode):
    op: ClassVar[str] = "add"


@dataclass(eq=False, kw_only=True)
class SubNode(OperationNode):
    op: ClassVar[str] = "sub"


@dataclass(eq=False, kw_only=True)
class MulNode(OperationNode):
    op: ClassVar[str] = "mul"


@dataclass(eq=False, kw_only=True)
class XorNode(OperationNode):
    op: ClassVar[str] = "xor"


@dataclass(eq=False, kw_only=True)
class AndNode(OperationNode):
    op: ClassVar[str] = "and"


@dataclass(eq=False, kw_only=True)
class OrNode(OperationNode):
    op: ClassVar[str] = "or"


@dataclass(eq=False, kw_only=True)
class ShlNode(OperationNode):
    op: ClassVar[str] = "shl"


@dataclass(eq=False, kw_only=True)
class ShrNode(OperationNode):
    op: ClassVar[str] = "shr"


@dataclass(eq=False, kw_only=True)
class EqNode(OperationNode):
    op: ClassVar[str] = "eq"


@dataclass(eq=False, kw_only=True)
class LtNode(OperationNode):
    op: ClassVar[str] = "lt"


@dataclass(eq=False, kw_only=True)
class VAddNode(OperationNode):
    op: ClassVar[str] = "vadd"


@dataclass(eq=False, kw_only=True)
class VSubNode(OperationNode):
    op: ClassVar[str] = "vsub"


@dataclass(eq=False, kw_only=True)
class VMulNode(OperationNode):
    op: ClassVar[str] = "vmul"


@dataclass(eq=False, kw_only=True)
class VXorNode(OperationNode):
    op: ClassVar[str] = "vxor"


@dataclass(eq=False, kw_only=True)
class VAndNode(OperationNode):
    op: ClassVar[str] = "vand"


@dataclass(eq=False, kw_only=True)
class VOrNode(OperationNode):
    op: ClassVar[str] = "vor"


@dataclass(eq=False, kw_only=True)
class VShlNode(OperationNode):
    op: ClassVar[str] = "vshl"


@dataclass(eq=False, kw_only=True)
class VShrNode(OperationNode):
    op: ClassVar[str] = "vshr"


@dataclass(eq=False, kw_only=True)
class SplatNode(OperationNode):
    op: ClassVar[str] = "splat"


@dataclass(eq=False, kw_only=True)
class SelectNode(OperationNode):
    op: ClassVar[str] = "select"


@dataclass(eq=False, kw_only=True)
class VSelectNode(OperationNode):
    op: ClassVar[str] = "vselect"


_NODE_TYPES: dict[str, type[OperationNode]] = {
    node_type.op: node_type
    for node_type in (
        ConstNode, LoadNode, VLoadNode, StoreNode, VStoreNode,
        AddNode, SubNode, MulNode, XorNode, AndNode, OrNode, ShlNode, ShrNode,
        EqNode, LtNode, VAddNode, VSubNode, VMulNode, VXorNode, VAndNode,
        VOrNode, VShlNode, VShrNode, SplatNode, SelectNode, VSelectNode,
    )
}


def _connect(predecessor: Node, successor: Node, delay: int) -> None:
    """Merge duplicate constraints, keeping the strongest delay both ways."""
    delay = max(delay, successor.predecessors.get(predecessor, 0))
    successor.predecessors[predecessor] = delay
    predecessor.successors[successor] = delay


@dataclass
class OperationDAG:
    """Typed operations and synthetic initial stores, without a schedule.

    ``operations[id]`` preserves the input's ID indexing. ``nodes`` includes
    the initial stores first, followed by the original operations. Construct
    with ``OperationDAG.from_program(machine.load_program(path))`` or pass a
    JSON string to ``OperationDAG.from_json(text)``.
    """

    name: str
    initial_stores: dict[str, InitialStoreNode]
    operations: tuple[OperationNode, ...]

    @property
    def nodes(self) -> tuple[Node, ...]:
        return (*self.initial_stores.values(), *self.operations)

    def writes(self, buffer: str) -> list[InitialStoreNode | StoreNode | VStoreNode]:
        """Return writes in version order, including the full-range write zero.

        The write defining a load's buffer version is
        ``dag.writes(load.buffer)[load.version]``; unchanged words may come
        from earlier writes when that defining write covers only a subrange.
        Unknown buffer names raise KeyError.
        """
        return [self.initial_stores[buffer]] + [
            node for node in self.operations
            if isinstance(node, (StoreNode, VStoreNode)) and node.buffer == buffer
        ]

    @classmethod
    def from_json(cls, text: str) -> OperationDAG:
        return cls.from_program(json.loads(text))

    @classmethod
    def from_program(cls, program: dict) -> OperationDAG:
        """Build data and whole-buffer ordering links without changing the input.

        Loads depend on the current write. The next write depends on that
        write and all its readers, including accesses to disjoint ranges.
        """
        machine.validate_program(program)
        initial_stores = {
            name: InitialStoreNode(buffer=name, width=size)
            for name, size in program["buffers"].items()
        }
        current_writes: dict[str, InitialStoreNode | StoreNode | VStoreNode] = dict(
            initial_stores
        )
        readers: dict[str, list[MemoryNode]] = {name: [] for name in initial_stores}
        operations: list[OperationNode] = []
        producers: dict[str, OperationNode] = {}

        for operation in program["operations"]:
            opcode = operation["op"]
            fields = {
                "id": operation["id"],
                "dest": operation.get("dest"),
                "args": tuple(operation.get("args", [])),
            }
            if opcode == "const":
                fields["value"] = operation["value"]
            elif opcode in machine.MEMORY_OPS:
                buffer = operation["buffer"]
                version = current_writes[buffer].version
                fields.update(
                    buffer=buffer,
                    offset=operation["offset"],
                    width=machine.memory_width(operation),
                    version=version + 1 if opcode in machine.STORE_OPS else version,
                )
            node = _NODE_TYPES[opcode](**fields)

            for arg in node.args:
                producer = producers[arg]
                _connect(producer, node, producer.latency)
            if isinstance(node, MemoryNode):
                previous_write = current_writes[node.buffer]
                _connect(previous_write, node, previous_write.latency)
                if isinstance(node, (StoreNode, VStoreNode)):
                    for reader in readers[node.buffer]:
                        _connect(reader, node, 1)
                    current_writes[node.buffer] = node
                    readers[node.buffer].clear()
                else:
                    readers[node.buffer].append(node)

            operations.append(node)
            if node.dest is not None:
                producers[node.dest] = node

        return cls(
            name=program["name"],
            initial_stores=initial_stores,
            operations=tuple(operations),
        )


def allocate_scratch(program: dict) -> dict[str, int]:
    """Assign scratch addresses to every SSA result."""

    # A simple non-overlapping allocation. Vectors are placed first so their
    # alignment does not create holes between scalar values.
    scratch: dict[str, int] = {}
    cursor = 0
    operations = program["operations"]

    for result_kind in ("vector", "scalar"):
        for operation in operations:
            spec = machine.OP_SPECS[operation["op"]]
            if spec["result"] != result_kind:
                continue
            dest = operation["dest"]
            if result_kind == "vector":
                cursor = machine.align_up(cursor, machine.VLEN)
                scratch[dest] = cursor
                cursor += machine.VLEN
            else:
                scratch[dest] = cursor
                cursor += 1

    if cursor > machine.SCRATCH_WORDS:
        raise machine.CompileError(
            f"program requires {cursor} scratch words, limit is {machine.SCRATCH_WORDS}"
        )

    return scratch


def earliest_issue_cycle(
    program: dict,
    operation: dict,
    producer: dict[str, int],
    issue_cycle: dict[int, int],
) -> int:
    """Find the earliest cycle allowed by data dependencies and memory ordering."""
    operations = program["operations"]
    earliest = 0

    for arg in operation.get("args", []):
        pred_id = producer[arg]
        pred = operations[pred_id]
        earliest = max(
            earliest,
            issue_cycle[pred_id] + machine.OP_SPECS[pred["op"]]["latency"],
        )

    for pred_id in machine.memory_predecessors(program, operation["id"]):
        earliest = max(earliest, issue_cycle[pred_id] + 1)

    return earliest


def schedule_operations(program: dict) -> list[dict[str, list[int]]]:
    """Greedily fill bundles in source order, stalling when necessary."""
    operations = program["operations"]

    bundles: list[dict[str, list[int]]] = []
    curr_bundle: dict[str, list[int]] = {}
    issue_cycle: dict[int, int] = {}
    producer = machine.producer_map(program)

    for operation in operations:
        engine = machine.OP_SPECS[operation["op"]]["engine"]
        earliest = earliest_issue_cycle(program, operation, producer, issue_cycle)

        # Flush the current bundle, then emit empty stalls until this op is ready.
        while (
            len(bundles) < earliest
            or len(curr_bundle.get(engine, [])) >= machine.ENGINE_LIMITS[engine]
        ):
            bundles.append(curr_bundle)
            curr_bundle = {}

        curr_bundle.setdefault(engine, []).append(operation["id"])
        issue_cycle[operation["id"]] = len(bundles)

    if curr_bundle:
        bundles.append(curr_bundle)

    return bundles


def compile_program(program: dict) -> dict:
    """Compile one validated IR program into scratch allocations and bundles."""
    scratch = allocate_scratch(program)
    bundles = schedule_operations(program)
    return {"scratch": scratch, "bundles": bundles}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python3 compiler.py <program.json>", file=sys.stderr)
        return 2

    program = machine.load_program(argv[0])
    compilation = compile_program(program)
    machine.check_compilation(program, compilation)
    json.dump(compilation, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

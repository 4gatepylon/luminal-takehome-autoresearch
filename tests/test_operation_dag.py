"""Tests for the operation graph, separate from the supplied machine tests."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import is_dataclass
from pathlib import Path

import compiler
import machine


def memory_program() -> dict:
    return {
        "name": "buffer_versions",
        "buffers": {"data": 24, "other": 8, "unused": 5},
        "operations": [
            {"id": 0, "op": "const", "dest": "seed", "value": 9},
            {"id": 1, "op": "load", "dest": "before", "buffer": "data", "offset": 0},
            {"id": 2, "op": "load", "dest": "peer", "buffer": "data", "offset": 1},
            {"id": 3, "op": "store", "args": ["seed"], "buffer": "data", "offset": 16},
            {"id": 4, "op": "vload", "dest": "block", "buffer": "data", "offset": 0},
            {"id": 5, "op": "load", "dest": "after", "buffer": "data", "offset": 23},
            {"id": 6, "op": "vstore", "args": ["block"], "buffer": "data", "offset": 8},
            {"id": 7, "op": "vload", "dest": "final", "buffer": "data", "offset": 16},
            {"id": 8, "op": "store", "args": ["seed"], "buffer": "other", "offset": 7},
            {"id": 9, "op": "store", "args": ["seed"], "buffer": "data", "offset": 23},
        ],
        "cases": [{"data": list(range(24)), "other": [0] * 8, "unused": [0] * 5}],
    }


class OperationDAGTests(unittest.TestCase):
    def assert_graph_links(self, dag):
        positions = {node: index for index, node in enumerate(dag.nodes)}
        for node in dag.nodes:
            for predecessor, delay in node.predecessors.items():
                self.assertLess(positions[predecessor], positions[node])
                self.assertEqual(predecessor.successors[node], delay)
            for successor, delay in node.successors.items():
                self.assertEqual(successor.predecessors[node], delay)

    def test_every_opcode_has_a_distinct_dataclass(self):
        expected_types = {
            "const": compiler.ConstNode,
            "load": compiler.LoadNode,
            "vload": compiler.VLoadNode,
            "store": compiler.StoreNode,
            "vstore": compiler.VStoreNode,
            "add": compiler.AddNode,
            "sub": compiler.SubNode,
            "mul": compiler.MulNode,
            "xor": compiler.XorNode,
            "and": compiler.AndNode,
            "or": compiler.OrNode,
            "shl": compiler.ShlNode,
            "shr": compiler.ShrNode,
            "eq": compiler.EqNode,
            "lt": compiler.LtNode,
            "vadd": compiler.VAddNode,
            "vsub": compiler.VSubNode,
            "vmul": compiler.VMulNode,
            "vxor": compiler.VXorNode,
            "vand": compiler.VAndNode,
            "vor": compiler.VOrNode,
            "vshl": compiler.VShlNode,
            "vshr": compiler.VShrNode,
            "splat": compiler.SplatNode,
            "select": compiler.SelectNode,
            "vselect": compiler.VSelectNode,
        }
        self.assertEqual(set(expected_types), set(machine.OP_SPECS))
        self.assertEqual(len(set(expected_types.values())), len(expected_types))
        operations = [
            {"id": 0, "op": "const", "dest": "scalar", "value": 7},
            {"id": 1, "op": "splat", "dest": "vector", "args": ["scalar"]},
        ]
        for opcode, spec in machine.OP_SPECS.items():
            operation = {"id": len(operations), "op": opcode, "args": list(spec["args"])}
            if spec["result"] is not None:
                operation["dest"] = f"result_{opcode}"
            if opcode == "const":
                operation["value"] = 123
            elif opcode in machine.MEMORY_OPS:
                operation.update(buffer="data", offset=0)
            operations.append(operation)
        program = {
            "name": "all_opcodes", "buffers": {"data": 8},
            "operations": operations, "cases": [{"data": list(range(8))}],
        }
        dag = compiler.OperationDAG.from_program(program)
        for operation, node in zip(operations, dag.operations):
            with self.subTest(opcode=operation["op"]):
                self.assertIs(type(node), expected_types[operation["op"]])
                self.assertTrue(is_dataclass(node))
                self.assertEqual(node.id, operation["id"])
                self.assertEqual(node.args, tuple(operation.get("args", [])))
                self.assertEqual(node.dest, operation.get("dest"))
                self.assertEqual(node.latency, machine.OP_SPECS[node.op]["latency"])
                self.assertEqual(node.engine, machine.OP_SPECS[node.op]["engine"])
        self.assertEqual(dag.operations[2].value, 123)
        self.assert_graph_links(dag)

    def test_initial_stores_and_per_buffer_write_history(self):
        dag = compiler.OperationDAG.from_program(memory_program())
        self.assertEqual(dag.nodes[:3], tuple(dag.initial_stores.values()))
        for name, width in memory_program()["buffers"].items():
            initial = dag.initial_stores[name]
            self.assertEqual(initial.version, 0)
            self.assertEqual(initial.latency, 0)
            self.assertEqual(initial.address_range, (0, width))
            self.assertEqual(initial.predecessors, {})
        writes = dag.writes("data")
        self.assertEqual(writes, [dag.initial_stores["data"], *(dag.operations[i] for i in (3, 6, 9))])
        self.assertEqual([node.version for node in writes], [0, 1, 2, 3])
        self.assertEqual([node.address_range for node in writes], [(0, 24), (16, 17), (8, 16), (23, 24)])
        self.assertEqual([node.version for node in dag.writes("other")], [0, 1])
        self.assertEqual(dag.writes("unused"), [dag.initial_stores["unused"]])
        with self.assertRaises(KeyError):
            dag.writes("missing")

    def test_versions_order_disjoint_accesses_and_preserve_read_parallelism(self):
        dag = compiler.OperationDAG.from_program(memory_program())
        seed, before, peer, store, block, after, vstore, final, other, last = dag.operations
        initial = dag.initial_stores["data"]
        self.assertEqual(before.predecessors, {initial: 0})
        self.assertEqual(peer.predecessors, {initial: 0})
        self.assertEqual(store.predecessors, {seed: 1, initial: 0, before: 1, peer: 1})
        self.assertEqual(block.predecessors, {store: 1})
        self.assertEqual(after.predecessors, {store: 1})
        # The data edge takes precedence over the one-cycle memory-order edge.
        self.assertEqual(vstore.predecessors, {block: 4, store: 1, after: 1})
        self.assertEqual(final.predecessors, {vstore: 1})
        self.assertEqual(other.predecessors, {seed: 1, dag.initial_stores["other"]: 0})
        self.assertEqual(last.predecessors, {seed: 1, vstore: 1, final: 1})
        for load, version in ((before, 0), (peer, 0), (block, 1), (after, 1), (final, 2)):
            self.assertEqual(load.version, version)
            self.assertIn(dag.writes(load.buffer)[version], load.predecessors)
        self.assertEqual(block.address_range, (0, 8))
        self.assertEqual(after.address_range, (23, 24))
        self.assert_graph_links(dag)

    def test_repeated_operands_keep_order_without_duplicate_edges(self):
        program = {
            "name": "repeated_args", "buffers": {"out": 1},
            "operations": [
                {"id": 0, "op": "const", "dest": "a", "value": 4},
                {"id": 1, "op": "mul", "dest": "b", "args": ["a", "a"]},
                {"id": 2, "op": "sub", "dest": "c", "args": ["b", "a"]},
            ],
            "cases": [{"out": [0]}],
        }
        dag = compiler.OperationDAG.from_program(program)
        a, b, c = dag.operations
        self.assertEqual(b.args, ("a", "a"))
        self.assertEqual(b.predecessors, {a: 1})
        self.assertEqual(c.args, ("b", "a"))
        self.assertEqual(c.predecessors, {b: 2, a: 1})
        self.assert_graph_links(dag)

    def test_public_programs_build_without_mutating_input(self):
        for path in sorted((Path(__file__).parents[1] / "programs").glob("*.json")):
            with self.subTest(program=path.name):
                program = machine.load_program(path)
                original = deepcopy(program)
                dag = compiler.OperationDAG.from_program(program)
                self.assertEqual(program, original)
                self.assertEqual(len(dag.operations), len(program["operations"]))
                self.assert_graph_links(dag)

    def test_json_entrypoint_and_validation(self):
        program = memory_program()
        dag = compiler.OperationDAG.from_json(json.dumps(program))
        self.assertEqual(dag.name, program["name"])
        self.assertEqual(len(dag.operations), len(program["operations"]))
        program["operations"][0]["op"] = "unknown"
        with self.assertRaises(machine.ProgramError):
            compiler.OperationDAG.from_program(program)


if __name__ == "__main__":
    unittest.main()

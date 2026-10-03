"""Tests score grouping, single evaluation per file, and strategy forwarding."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import score


class ScoreGroupTests(unittest.TestCase):
    def test_overlapping_groups_reuse_results_and_all_includes_ungrouped_files(self):
        with tempfile.TemporaryDirectory() as directory:
            program_dir = Path(directory)
            for filename in ("a.json", "b.json", "extra/c.json"):
                path = program_dir / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({
                    "name": filename, "buffers": {"out": 1},
                    "operations": [
                        {"id": 0, "op": "const", "dest": "a", "value": 6},
                        {"id": 1, "op": "const", "dest": "b", "value": 7},
                        {"id": 2, "op": "mul", "dest": "product", "args": ["a", "b"]},
                        {"id": 3, "op": "store", "args": ["product"], "buffer": "out", "offset": 0},
                    ],
                    "cases": [{"out": [0]}],
                }))
            # Controlled valid schedules isolate aggregation from compiler heuristics.
            def compile_example(program, scratch_allocation_strategy):
                if program["name"] == "a.json":
                    return {
                        "scratch": {"a": 0, "b": 1, "product": 0},
                        "bundles": [{"load": [0, 1]}, {"scalar": [2]}, {}, {"store": [3]}],
                    }
                return original_serial_compile(program)

            original_serial_compile = score.machine.serial_compile
            for strategy in (None, "first-fit", "disjoint"):
                output = io.StringIO()
                with (
                    self.subTest(strategy=strategy),
                    patch.object(score, "PROGRAM_DIR", program_dir),
                    patch.object(score, "PROGRAM_GROUPS", {"original": ["a.json", "b.json"], "overlap": ["a.json"]}),
                    patch.object(score, "compile_program", side_effect=compile_example) as compile_program,
                    patch.object(score.machine, "serial_compile", wraps=original_serial_compile) as serial_compile,
                    redirect_stdout(output),
                ):
                    score.main([] if strategy is None else ["--strategy", strategy])
                self.assertEqual([call.args[0]["name"] for call in compile_program.call_args_list],
                                 ["a.json", "b.json", "extra/c.json"])
                self.assertTrue(all(call.kwargs["scratch_allocation_strategy"] == strategy
                                    for call in compile_program.call_args_list))
                self.assertEqual(serial_compile.call_count, 3)
                report = output.getvalue()
                for heading, count, combined in (("original", 2, "1.170"), ("overlap", 1, "1.369"), ("all", 3, "1.110")):
                    section = report.split(f"aggregate for {heading} ({count} programs):\n")[1].split("\n\n")[0]
                    self.assertIn(f"combined score: {combined}x", section)

    def test_missing_group_file_fails_before_evaluation(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(score, "PROGRAM_DIR", Path(directory)),
            patch.object(score, "PROGRAM_GROUPS", {"original": ["missing.json"]}),
            patch.object(score, "compile_program") as compile_program,
        ):
            with self.assertRaisesRegex(ValueError, "missing programs"):
                score.main([])
            compile_program.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Implemented by Codex (GPT-6).

Real Git and subprocess tests; evaluator command construction is mocked."""

from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from autoresearch.environment import (
    codex_command,
    evaluate,
    execute,
    git,
    validate_artifact,
)
from tests.autoresearch.support import create_repository


class GitEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.repository = create_repository(self.root / "repo")
        self.base = self.repository.resolve("main")

    def test_proposal_commit_preserves_dirty_original_and_retains_branch(self):
        compiler = self.repository.root / "compiler.py"
        compiler.write_text("# user's uncommitted work\n")
        with self.repository.worktree(self.base, "proposal") as path:
            self.assertNotEqual(path, self.repository.root)
            self.assertEqual((path / "compiler.py").read_text(), "# original compiler\n")
            self.assertFalse(validate_artifact(path, self.base, "proposal"))
            (path / "compiler.py").write_text("# proposed compiler\n")
            self.assertTrue(validate_artifact(path, self.base, "proposal"))
            commit = self.repository.commit_compiler(path, "run", 1, model="test-model", effort="low")
            self.assertFalse(validate_artifact(path, commit, "proposal"))
        self.assertFalse(path.exists())
        self.assertEqual(self.repository.resolve("proposal"), commit)
        self.assertEqual(compiler.read_text(), "# user's uncommitted work\n")
        self.assertIn("Implemented by Codex (test-model, reasoning effort: low).", git(self.repository.root, "show", "-s", "--format=%B", commit))

    def test_worktree_cleanup_on_exception_and_interruption(self):
        for error in (RuntimeError("failure"), KeyboardInterrupt()):
            with self.subTest(error=type(error)), self.assertRaises(type(error)):
                with self.repository.worktree(self.base) as path:
                    (path / "compiler.py").write_text("# dirty\n")
                    raise error
            self.assertFalse(path.exists())
            self.assertEqual(git(self.repository.root, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_rejects_staged_change_hidden_by_restoring_working_copy(self):
        with self.repository.worktree(self.base) as path:
            original = (path / "machine.py").read_text()
            (path / "machine.py").write_text("# staged evaluator tampering\n")
            git(path, "add", "machine.py")
            (path / "machine.py").write_text(original)
            with self.assertRaisesRegex(RuntimeError, "outside compiler.py"):
                validate_artifact(path, self.base, "")

    def test_rejects_other_files_including_ignored_files(self):
        for filename in ("machine.py", "extra.txt", "ignored.txt"):
            with self.subTest(filename=filename), self.repository.worktree(self.base) as path:
                (path / filename).write_text("tampered\n")
                with self.assertRaisesRegex(RuntimeError, "outside compiler.py"):
                    validate_artifact(path, self.base, "")

    def test_rejects_missing_or_symlinked_compiler(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink), self.repository.worktree(self.base) as path:
                (path / "compiler.py").unlink()
                if symlink:
                    (path / "compiler.py").symlink_to(path / "machine.py")
                with self.assertRaisesRegex(RuntimeError, "regular file"):
                    validate_artifact(path, self.base, "")

    def test_rejects_agent_commit_and_branch_switch(self):
        with self.repository.worktree(self.base) as path:
            git(path, "commit", "--allow-empty", "-m", "Unauthorized commit")
            with self.assertRaisesRegex(RuntimeError, "changed HEAD"):
                validate_artifact(path, self.base, "")
        with self.repository.worktree(self.base) as path:
            git(path, "switch", "-c", "unexpected")
            with self.assertRaisesRegex(RuntimeError, "switched branches"):
                validate_artifact(path, self.base, "")


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.log = self.path / "command.log"

    def test_stdin_output_and_failure_log(self):
        execute([sys.executable, "-B", "-c", "import sys; print(sys.stdin.read())"], self.path, self.log, 10, "prompt text")
        self.assertIn("prompt text", self.log.read_text())
        with self.assertRaisesRegex(RuntimeError, "exited 7"):
            execute([sys.executable, "-B", "-c", "print('diagnostic'); raise SystemExit(7)"], self.path, self.log, 10)
        self.assertIn("diagnostic", self.log.read_text())

    def test_timeout_stops_process_group(self):
        marker = self.path / "surviving-child.txt"
        child_script = (
            f"import time; from pathlib import Path; print('ready', flush=True); time.sleep(3); Path({str(marker)!r}).write_text('still alive')"
        )
        script = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-B', '-c', {child_script!r}]); time.sleep(60)"
        with self.assertRaises(subprocess.TimeoutExpired):
            execute([sys.executable, "-B", "-c", script], self.path, self.log, 2)
        self.assertIn("ready", self.log.read_text())
        time.sleep(2)
        self.assertFalse(marker.exists(), "Timed-out command left its child running")

    def test_agent_command_keeps_sandbox_and_disables_parallel_agents(self):
        command = codex_command(self.path, "model", "high")
        self.assertEqual(command[command.index("--ask-for-approval") + 1], "never")
        self.assertNotIn("--sandbox", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn('web_search="disabled"', command)
        for feature in ("multi_agent", "multi_agent_v2", "apps", "plugins", "browser_use", "computer_use"):
            self.assertEqual(command[command.index(feature) - 1], "--disable")
        policy = next(arg for arg in command if arg.startswith("permissions.luminal_compiler="))
        self.assertIn(str(self.path.resolve() / "compiler.py"), policy)
        self.assertIn('extends=":read-only"', policy)
        self.assertIn("network={enabled=false}", policy)

    def test_evaluation_only_runs_compiler_tests_in_read_only_sandbox(self):
        output = "public geometric-mean speedup: 1.500x\npublic geometric-mean scratch reduction: 1.200x\npublic combined score: 1.342x\n"

        def command_output(command, cwd, log, timeout):
            # Test diagnostics must never supply the benchmark's recorded metrics.
            log.write_text(output if command[-1] == "score.py" else output.replace("1.342x", "9.000x"))

        with patch("autoresearch.environment.execute", side_effect=command_output) as run:
            metrics = evaluate(self.path, self.path, 10)
        self.assertEqual(metrics["combined_score"], 1.342)
        self.assertEqual(len(run.call_args_list), 2)
        for call in run.call_args_list:
            command = call.args[0]
            self.assertEqual(command[:2], ["codex", "sandbox"])
            self.assertEqual(command[command.index("--permission-profile") + 1], ":read-only")
        tests = run.call_args_list[0].args[0]
        self.assertEqual(tests[-2:], ["tests.test_machine", "tests.test_public_programs"])
        self.assertNotIn("discover", tests)
        self.assertIn("9.000x", (self.path / "tests.log").read_text())
        self.assertEqual((self.path / "score.log").read_text(), output)

    def test_evaluation_rejects_missing_duplicate_and_nonfinite_metrics(self):
        output = "public geometric-mean speedup: 1.500x\npublic geometric-mean scratch reduction: 1.200x\npublic combined score: 1.342x\n"
        for invalid in ("", output * 2, output.replace("1.342x", "0.000x"), output.replace("1.342x", "nanx"), output.replace("1.342", "9" * 400 + ".000")):
            with self.subTest(invalid=invalid):
                def command_output(command, cwd, log, timeout):
                    log.write_text(invalid if command[-1] == "score.py" else output)

                with patch("autoresearch.environment.execute", side_effect=command_output), self.assertRaisesRegex(RuntimeError, "Missing or invalid"):
                    evaluate(self.path, self.path, 10)

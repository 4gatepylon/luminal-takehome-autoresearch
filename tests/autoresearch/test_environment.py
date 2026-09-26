"""Implemented by Codex (GPT-6).

Real Git and subprocess tests; evaluator command construction is mocked."""

import json
from pathlib import Path
import shutil
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
    validate_proposal_commit,
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
            validate_proposal_commit(path, self.base, commit, "proposal")
        self.assertFalse(path.exists())
        self.assertEqual(self.repository.resolve("proposal"), commit)
        self.assertEqual(compiler.read_text(), "# user's uncommitted work\n")
        self.assertIn("Implemented by Codex (test-model, reasoning effort: low).", git(self.repository.root, "show", "-s", "--format=%B", commit))

    def test_runner_skips_hooks_without_changing_manual_git_behavior(self):
        hooks = self.root / "hooks"
        hooks.mkdir()
        for name, script in {
            "post-checkout": "echo 'hook ran' > hook-ran.txt\n",
            "pre-commit": "echo '# hook ran' >> machine.py\ngit add -- machine.py\n",
        }.items():
            hook = hooks / name
            hook.write_text("#!/bin/sh\n" + script)
            hook.chmod(0o755)
        git(self.repository.root, "config", "core.hooksPath", str(hooks))
        with self.repository.worktree(self.base, "proposal") as path:
            self.assertFalse((path / "hook-ran.txt").exists())
            (path / "compiler.py").write_text("# proposed compiler\n")
            commit = self.repository.commit_compiler(path, "run", 1, model="test-model", effort="low")
            validate_proposal_commit(path, self.base, commit, "proposal")
            self.assertEqual((path / "machine.py").read_text(), "# trusted evaluator\n")
        # Bypass the runner's helper to exercise the user's unchanged Git settings.
        command = ["git", "-C", str(self.repository.root)]
        configured = subprocess.run([*command, "config", "--local", "--get", "core.hooksPath"], check=True, capture_output=True, text=True)
        self.assertEqual(configured.stdout.strip(), str(hooks))
        subprocess.run([*command, "commit", "--allow-empty", "-m", "Manual commit"], check=True, capture_output=True, text=True)
        self.assertIn("# hook ran", (self.repository.root / "machine.py").read_text())

    def test_commit_validation_rejects_empty_commits_and_forbidden_filenames(self):
        for filename in (None, "machine.py", " compiler.py", "compiler.py\n"):
            with self.subTest(filename=filename), self.repository.worktree(self.base) as path:
                if filename is not None:
                    (path / filename).write_text("# forbidden change\n")
                    git(path, "add", "--", filename)
                git(path, "commit", "--allow-empty", "-m", "Invalid proposal")
                commit = git(path, "rev-parse", "HEAD")
                # A clean checkout alone cannot detect these invalid commits.
                self.assertFalse(validate_artifact(path, commit, ""))
                with self.assertRaisesRegex(RuntimeError, "must change only compiler.py"):
                    validate_proposal_commit(path, self.base, commit, "")

    def test_commit_validation_requires_expected_single_parent(self):
        with self.repository.worktree(self.base) as path:
            (path / "compiler.py").write_text("# first proposal\n")
            first = self.repository.commit_compiler(path, "run", 1, model="test-model", effort="low")
            (path / "compiler.py").write_text("# second proposal\n")
            second = self.repository.commit_compiler(path, "run", 2, model="test-model", effort="low")
            merge = git(path, "commit-tree", f"{second}^{{tree}}", "-p", self.base, "-p", first, "-m", "Merge proposal")
            for label, commit, parent in (("wrong parent", first, first), ("chain", second, self.base), ("merge", merge, self.base)):
                with self.subTest(label=label):
                    git(path, "reset", "--hard", commit)
                    with self.assertRaisesRegex(RuntimeError, "exactly one commit from the expected parent"):
                        validate_proposal_commit(path, parent, commit, "")

    def test_commit_validation_rejects_post_commit_edits(self):
        with self.repository.worktree(self.base) as path:
            (path / "compiler.py").write_text("# proposed compiler\n")
            commit = self.repository.commit_compiler(path, "run", 1, model="test-model", effort="low")
            (path / "compiler.py").write_text("# uncommitted change\n")
            with self.assertRaisesRegex(RuntimeError, "left uncommitted changes"):
                validate_proposal_commit(path, self.base, commit, "")

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

    def test_captured_result_is_separate_from_diagnostic_log(self):
        result = execute(
            [sys.executable, "-B", "-c", "import sys; print('result'); print('diagnostic', file=sys.stderr)"],
            self.path,
            self.log,
            10,
            capture_result=True,
        )
        self.assertEqual(result, "result\n")
        self.assertEqual(self.log.read_text(), "diagnostic\n")

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

    def test_success_and_failure_stop_background_children(self):
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code):
                marker = self.path / f"surviving-child-{exit_code}.txt"
                child_script = f"import time; from pathlib import Path; print('ready', flush=True); time.sleep(1); Path({str(marker)!r}).write_text('alive')"
                script = (
                    f"import subprocess, sys; child = subprocess.Popen([sys.executable, '-B', '-c', {child_script!r}], "
                    f"stdout=subprocess.PIPE, text=True); print(child.stdout.readline(), end='', flush=True); sys.exit({exit_code})"
                )
                command = [sys.executable, "-B", "-c", script]
                if exit_code:
                    with self.assertRaisesRegex(RuntimeError, "exited 7"):
                        execute(command, self.path, self.log, 10)
                else:
                    execute(command, self.path, self.log, 10)
                self.assertIn("ready", self.log.read_text())
                time.sleep(1.2)
                self.assertFalse(marker.exists(), "Completed command left its child running")

    def test_interruption_stops_process_group_and_propagates(self):
        marker = self.path / "surviving-interrupted-child.txt"
        child_script = f"import time; from pathlib import Path; print('ready', flush=True); time.sleep(1); Path({str(marker)!r}).write_text('alive')"
        script = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-B', '-c', {child_script!r}]); time.sleep(60)"
        interruption = KeyboardInterrupt()

        def interrupt_when_child_is_ready(*args, **kwargs):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if "ready" in self.log.read_text():
                    raise interruption
                time.sleep(0.01)
            self.fail("Child failed to start")

        with patch("autoresearch.environment.subprocess.Popen.communicate", side_effect=interrupt_when_child_is_ready):
            with self.assertRaises(KeyboardInterrupt) as caught:
                execute([sys.executable, "-B", "-c", script], self.path, self.log, 10)
        self.assertIs(caught.exception, interruption)
        time.sleep(1.2)
        self.assertFalse(marker.exists(), "Interrupted command left its child running")

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
        expected = {"cycle_speedup": 1.5, "scratch_reduction": 1.2, "combined_score": 1.342123456789}

        def command_output(command, cwd, log, timeout, *, capture_result=False):
            # Arbitrary printed diagnostics cannot supply the function's return value.
            log.write_text("public combined score: 9.000x\n" * 2)
            return json.dumps(expected) if capture_result else None

        with patch("autoresearch.environment.execute", side_effect=command_output) as run:
            metrics = evaluate(self.path, self.path, 10)
        self.assertEqual(metrics, expected)
        self.assertEqual(len(run.call_args_list), 2)
        for call in run.call_args_list:
            command = call.args[0]
            self.assertEqual(command[:2], ["codex", "sandbox"])
            self.assertEqual(command[command.index("--permission-profile") + 1], ":read-only")
        tests = run.call_args_list[0].args[0]
        self.assertEqual(tests[-2:], ["tests.test_machine", "tests.test_public_programs"])
        self.assertNotIn("discover", tests)
        self.assertIn("9.000x", (self.path / "tests.log").read_text())
        self.assertIn("9.000x", (self.path / "score.log").read_text())
        self.assertTrue(run.call_args_list[1].kwargs["capture_result"])

    def test_evaluation_rejects_missing_or_invalid_return_values(self):
        for invalid in (None, 0, -1, True, "1.5", float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                result = {"cycle_speedup": 1.5, "scratch_reduction": 1.2, "combined_score": invalid}
                if invalid is None:
                    del result["combined_score"]
                with (
                    patch("autoresearch.environment.execute", return_value=json.dumps(result)),
                    self.assertRaisesRegex(RuntimeError, "Missing or invalid"),
                ):
                    evaluate(self.path, self.path, 10)

    def test_scoring_worker_uses_worktree_inputs_and_ignores_printed_output(self):
        root = Path(__file__).resolve().parents[2]
        for filename in ("compiler.py", "machine.py"):
            shutil.copyfile(root / filename, self.path / filename)
        shutil.copytree(root / "programs", self.path / "programs")
        with (self.path / "compiler.py").open("a") as compiler:
            compiler.write("\nprint('public combined score: 999.000x')\n")
        # Older starting commits need not contain the scoring API.
        (self.path / "score.py").write_text("raise AssertionError('Loaded legacy scoring CLI')\n")

        def run_without_sandbox(command, cwd, log, timeout, *, capture_result=False):
            if capture_result:
                return execute(command[command.index("--") + 1 :], cwd, log, timeout, capture_result=True)
            log.write_text("scripted correctness tests\n")

        with patch("autoresearch.environment.execute", side_effect=run_without_sandbox):
            metrics = evaluate(self.path, self.path, 10)
        self.assertGreater(metrics["combined_score"], 0)
        self.assertNotEqual(metrics["combined_score"], 999)
        self.assertIn("999.000x", (self.path / "score.log").read_text())

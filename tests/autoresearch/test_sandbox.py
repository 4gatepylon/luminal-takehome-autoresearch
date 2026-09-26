"""Opt-in real Codex OS sandbox probes; these never invoke a model."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

from autoresearch.environment import compiler_permission_args


@unittest.skipUnless(os.environ.get("AUTORESEARCH_SANDBOX_TESTS") == "1",
                     "Set AUTORESEARCH_SANDBOX_TESTS=1 for real OS sandbox probes")
class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name).resolve()
        (self.path / "compiler.py").write_text("# compiler\n")
        (self.path / "machine.py").write_text("# evaluator\n")

    def run_probe(self, code, *, writable_compiler=True):
        policy = compiler_permission_args(self.path) if writable_compiler else []
        profile = "luminal_compiler" if writable_compiler else ":read-only"
        result = subprocess.run(
            ["codex", "sandbox", "--include-managed-config", *policy,
             "--permission-profile", profile, "--cd", str(self.path), "--",
             sys.executable, "-B", "-c", code],
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_only_compiler_is_writable(self):
        self.run_probe("""from pathlib import Path
assert Path('machine.py').read_text() == '# evaluator\\n'
Path('compiler.py').write_text('# changed\\n')
for target in ('machine.py', 'extra.txt'):
    try:
        Path(target).write_text('forbidden')
    except PermissionError:
        pass
    else:
        raise AssertionError(f'Unexpected write access: {target}')
""")

    def test_evaluation_cannot_write_compiler(self):
        self.run_probe("""from pathlib import Path
try:
    Path('compiler.py').write_text('forbidden')
except PermissionError:
    pass
else:
    raise AssertionError('Read-only evaluation wrote compiler.py')
""", writable_compiler=False)

    def test_shell_network_is_blocked(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.run_probe(f"""import socket
try:
    socket.create_connection(('127.0.0.1', {port}), timeout=2)
except PermissionError:
    pass
else:
    raise AssertionError('Sandbox connected to host listener')
""")

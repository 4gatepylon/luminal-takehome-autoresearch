"""Disposable fixtures; no tests modify this repository's Git history."""

from pathlib import Path

from autoresearch.environment import GitRepository, git


def create_repository(root: Path) -> GitRepository:
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Autoresearch test")
    git(root, "config", "user.email", "autoresearch@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.hooksPath", "/dev/null")
    (root / "compiler.py").write_text("# original compiler\n")
    (root / "machine.py").write_text("# trusted evaluator\n")
    (root / ".gitignore").write_text("ignored.txt\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "Test fixture")
    return GitRepository(root)

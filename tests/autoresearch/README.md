# Autoresearch tests

From the repository root, with requirements installed:

```sh
python -B -m unittest discover -s tests/autoresearch -t . -v
```

`test_database.py` exercises persistence, separate start/finish commits, duplicate
keys, null failure metrics, and recent-history filtering using real temporary
DuckDB databases. It does not invoke Codex or test sandbox enforcement.

The unchanged compiler tests live in `tests/test_machine.py` and
`tests/test_public_programs.py`. The runner evaluates only those two modules plus
`score.py`; infrastructure tests are never part of an experiment's fitness score.

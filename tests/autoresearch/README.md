# Autoresearch tests

From the repository root, with requirements installed:

```sh
python -B -m unittest discover -s tests/autoresearch -t . -v
```

`test_database.py` exercises persistence, separate start/finish commits, duplicate
keys, null failure metrics, recent-history filtering, and compatibility with the
original table using SQLAlchemy against real temporary DuckDB databases. It does
not invoke Codex or test sandbox enforcement.

`test_config.py` checks default hydration, precedence, YAML round-tripping, invalid
values, unknown keys, and rejection of Python object tags. It needs no database.

`test_cli.py` uses Click's test runner to check help, hydrated config output,
override precedence, validation errors, and the required Codex executable. Git
discovery and research execution are mocked; these tests make no model calls.

The unchanged compiler tests live in `tests/test_machine.py` and
`tests/test_public_programs.py`. The runner evaluates only those two modules plus
`score.py`; infrastructure tests are never part of an experiment's fitness score.

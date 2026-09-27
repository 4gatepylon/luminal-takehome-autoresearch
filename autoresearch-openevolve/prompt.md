Optimize compiler.py's general VLIW scheduling and scratch allocation.
Preserve compile_program(program) and the JSON-only CLI. Only this file evolves.
Use standard-library imports and machine; no file writes, network, or subprocesses.
Do not modify the input IR, monkeypatch machine, or special-case public programs.
Maximize the combined score; every case must remain correct.

{readme}

Read-only machine.py:
```python
{machine}
```

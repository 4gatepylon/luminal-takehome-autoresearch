Follow these instructions from agent_instructions.md:
{rules}

Improve this repository's compiler performance.
Read README.md, work/compiler.py, machine.py, and the supplied tests and programs.
Make one focused, general improvement to scheduling or scratch allocation.
Edit ONLY work/compiler.py. Do not create or modify any other files, including tests,
benchmarks, programs, machine.py, documentation, or Git configuration/history.
Do not commit or switch branches; the runner handles Git. Use only the standard
library. Do not hardcode public programs or alter evaluation behavior.
The filesystem is read-only except for the `work/` directory. Edit `work/compiler.py` in place;
do not create temporary files or bytecode caches. Run inline checks with -B.
Run {python} -B -m unittest -v tests.test_machine tests.test_public_programs and {python} -B score.py.
Maximize the public combined score while preserving correctness for arbitrary
valid inputs. The score equally weights cycle speedup and scratch reduction.
The current best combined score is {best_score:.3f}x. Try a new idea informed by
these recent attempts (iteration, status, score, error): {recent!r}
You have at most {codex_timeout:g} seconds. Finish with a short explanation
of your hypothesis, change, and measured result. Only work/compiler.py may change.

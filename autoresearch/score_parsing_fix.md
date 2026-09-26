# Score-parsing fix explained

Written by Codex (GPT-6).

## Current implementation: scoring is a library call

`score.py` now exposes an importable function:

```python
from score import score

metrics = score()
# {"cycle_speedup": ..., "scratch_reduction": ..., "combined_score": ...}
```

The function validates the public programs and returns full-precision numeric
metrics. It does not print the benchmark report by default. Running
`python score.py` still prints the original table and summary.

Autoresearch calls this function inside the existing read-only evaluator sandbox.
It loads the runner's scoring library but uses the worktree's compiler, machine,
and programs, so older starting commits need not contain the new API.

The returned dictionary is serialized as JSON solely to cross the subprocess
boundary. Printed diagnostics are redirected to `score.log` on a separate channel.
Neither `tests.log` nor `score.log` is read to obtain metrics. The parent validates
the returned numbers as positive and finite; metric labels, regex matching, and
printed precision no longer participate in scoring.

The tests cover the library/CLI contract, full-precision result transport, noisy
compiler output, and using the new scoring API with an older worktree.

## Historical issue and first fix (superseded)

Previously, the runner appended both commands' output to the same `eval.log`:

1. Run the correctness tests.
2. Run `score.py`.
3. Search the combined log for metric lines, taking the **first match** for each metric.

This happened because `execute()` opened the log in append mode, both calls
received the same log path, and `evaluate()` used `re.search()` on the complete
file. `re.search()` returns the first match; it has no information about which
command produced that line. I had coupled the human-readable execution log to
the machine-readable scoring input without preserving the source of each value.

For example:

```text
# Output from the tests:
public combined score: 9.000x

# Later output from score.py:
public combined score: 1.000x
```

The runner would record **9.000x**, even though the benchmark reported **1.000x**.
That could incorrectly make the proposal the starting point for subsequent attempts.
I reproduced this using simulated command output. Normal tests do not intentionally
print these lines, but compiler code runs during testing and can print arbitrary text.

The first fix made the output sources explicit:

```text
tests.log  <- correctness-test output; never used for scoring
score.log  <- benchmark output; parsed for metrics
```

For each of the three metrics—cycle speedup, scratch reduction, and combined
score—the parser then required:

- **Exactly one matching line.** Multiple matches fail evaluation instead of
  silently choosing one.
- **A positive, finite number.** Zero, negative, missing, or invalid values fail.
  The finite check also catches an extremely large numeric string that Python
  converts to infinity. Missing/nonpositive values were already rejected; duplicate
  detection and the explicit finite check are new.

An evaluation failure is recorded as a failed attempt, so it cannot become the
next best proposal. This fixes output mixing and ambiguous parsing; it is not a
guarantee against deliberate manipulation of the benchmark itself.

That first implementation was in `evaluate()` in [environment.py](environment.py).

The old evaluation test pre-populated the log with only valid benchmark output
and mocked command execution. It therefore did not exercise mixed test/benchmark
output or repeated metric lines. The first regression test gave the two commands
separate simulated outputs and checked that the benchmark values won; additional
cases rejected duplicated and overflowing numeric values.

This was a reproduced parser defect, not evidence that a real experiment had
already recorded a wrong score. Fixed in `619d550`; formatted in `0fc145e`.

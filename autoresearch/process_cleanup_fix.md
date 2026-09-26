# Process-cleanup fix

Written by Codex (GPT-6).

Status: implemented. Original issue reproduced at commit `ac11873`.

**Location:** `execute()` in [environment.py](environment.py), especially the
timeout/interrupt handler.

Previously, the helper started a process group but killed it only on timeout or
Ctrl-C. When the direct child exited normally or with an error, its children
could keep running. Waiting for the direct child did not stop the whole group.

**Reproduction:** Run a Python parent through `execute()`. Have it launch a child
that sleeps for half a second and writes a marker, then immediately exit. Repeat
with parent exit codes 0 and 7. Observed:

```text
Parent exit 0: execute returned; child wrote its marker afterward.
Parent exit 7: execute raised; child wrote its marker afterward.
```

Both children finished during the probe; neither was left running. This directly
reproduces the helper's behavior. It does not establish whether a particular Codex
version independently cleans up every child in a real agent session.

**Impact:** Background work can overlap validation, evaluation, or the next attempt
and consume resources after the runner considers a command finished. A surviving
process with compiler write access could race with validation or committing.

**Why tests missed it:** Child cleanup was tested for timeouts, but not normal exits
or nonzero exits.

**Implemented fix:** Process-group cleanup now runs in `finally` around
`process.communicate()`: success, nonzero exit, timeout, and interruption all
kill remaining group members and reap the direct child. `start_new_session=True`
isolates the group. A missing group is ignored; stdout, nonzero-exit reporting,
and the original timeout/interruption are preserved.

The existing SIGKILL policy is retained. Cleanup is unconditional, even when the
direct child has already exited.

**Regression tests:** [Process tests](../tests/autoresearch/test_environment.py)
launch real children that announce readiness and later write a marker. After
success, exit code 7, timeout, or interruption, no marker appears. Interruption
is injected after a real child starts; the original exception propagates.

This handles descendants that stay in the command's process group; it does not
contain a deliberately detached process that starts a different session.

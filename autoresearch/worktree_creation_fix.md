# Worktree-creation cleanup fix

Written by Codex (GPT-6).

Status: implemented. Original issue reproduced at commit `ac11873`.

**Location:** `GitRepository.worktree()` in [environment.py](environment.py).

Previously, `git worktree add` ran outside the cleanup guard. Creation could
partially succeed before reporting failure: a post-checkout hook could fail
after Git registered the worktree. The runner never invoked `git worktree remove`;
temporary-directory cleanup deleted the files but left Git's registration behind.
Hooks are now disabled separately; other partial-creation failures still needed
this lifecycle fix.

**Reproduction:** In a temporary repository, install a post-checkout hook that
exits with status 1, then enter `repository.worktree(...)`. Observed:

```text
worktree add exit: 1
Registered worktree count after failure: 2
Contains prunable entry: True
The extra registered directory no longer exists.
```

**Impact:** Failed attempts accumulate stale worktree registrations. Git can report
branches as associated with missing worktrees until those registrations are
removed or pruned. This is distinct from the earlier fix for recording a cleanup
failure's status: here the cleanup block is never entered.

**Why tests missed it:** Existing cleanup tests raised inside the worktree body,
after creation has succeeded; hooks are disabled by the fixture.

**Implemented fix:** Worktree creation now runs inside the guarded lifecycle:

```text
create temporary parent directory
try:
    git worktree add ...
    yield worktree to runner
finally:
    check whether Git registered this specific temporary worktree
    if registered: git worktree remove --force <that path>
remove temporary parent directory
```

The helper resolves its temporary path and checks Git's NUL-separated registration
records, even if the directory is missing. Only that exact worktree is removed;
there is no repository-wide prune. Proposal branches remain available.

If creation/the body already failed, a Git cleanup error is logged with its
traceback to the runner's stderr and the original exception still propagates.
Otherwise cleanup errors propagate normally, preventing successful selection.
An underlying Git cleanup failure or a machine crash can still leave stale metadata;
this fix adds no retries or crash recovery.

**Regression tests:** [Git tests](../tests/autoresearch/test_environment.py)
inject failures before/after registration and with a missing directory; they
check exact removal, untouched unrelated worktrees, and preserved original errors.
Cleanup-failure tests cover successful bodies, ordinary errors, timeout, and
interruption. [Runner integration](../tests/autoresearch/test_runner.py) verifies
a partial creation failure is recorded and the next attempt uses the prior best.
Git/DuckDB are real; agent/evaluator and Git failure points are scripted.

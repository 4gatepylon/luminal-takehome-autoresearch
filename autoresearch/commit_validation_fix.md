# Commit-validation fix

Written by Codex (GPT-6).

Status: implemented. Original issue reproduced at commit `ac11873`.

**Location:** `GitRepository.commit_compiler()` and `validate_artifact()` in
[environment.py](environment.py), and the commit/evaluation sequence in
[runner.py](runner.py).

Previously, the runner checked that only `compiler.py` changed before calling
`git commit`. Git then ran the host repository's hooks. A pre-commit hook could
modify and stage another file. After committing, the runner checked for
uncommitted changes against the new commit, but never compared that commit's
changes to its original parent. A clean working tree therefore passed even if
the commit included an evaluator modification.

**Reproduction:** In a temporary repository, install a pre-commit hook that writes
a comment to `machine.py` and stages it. Change only `compiler.py` in the proposal
worktree, run the normal validation, commit, and validate again. Observed:

```text
Pre-commit validation sees allowed proposal: True
Post-commit validation sees clean artifact: True
Actual files in proposal commit: ['compiler.py', 'machine.py']
```

The probe used a harmless comment, but showed that the compiler-only rule
was not enforced on the final commit. An evaluator change could affect subsequent
scores. This is a host-hook behavior problem; it does not demonstrate that the
sandboxed agent can write Git metadata or bypass its filesystem restrictions.

**Why tests missed it:** The shared test fixture sets `core.hooksPath` to
`/dev/null`. Existing scope tests exercise agent changes before committing.

**Implemented fix:** Runner-issued Git commands bypass local hooks, and one
validation call in `runner.py` checks the actual commit before evaluation:

1. The `git()` helper passes `-c core.hooksPath=/dev/null` on every invocation.
   This is a per-command override; it does not change the user's Git configuration
   or manual commit behavior. Automated worktree creation and proposal commits
   skip hooks.
2. `validate_proposal_commit(path, parent, commit, branch)` requires exactly one
   parent, equal to the expected starting commit; no chains or merges.
3. It compares the two commit trees and requires the changed-file set to be
   exactly `compiler.py`. NUL-separated names, preserved whitespace, and disabled
   rename detection keep filenames unambiguous. HEAD/branch must match, the
   checkout/index must be clean, and the compiler must remain a regular file.
4. A violation records a failed attempt, retaining its SHA/branch but skipping
   evaluation; it cannot be selected as the next parent.

**Regression tests:** [Git tests](../tests/autoresearch/test_environment.py)
exercise real hooks (runner skips them; manual Git still runs them), a valid
proposal, empty commits, forbidden/whitespace filenames, wrong parents, chains,
merges, and post-commit edits. [Runner integration](../tests/autoresearch/test_runner.py)
injects a forbidden commit-time change and checks the failed DB row, retained
SHA/branch, and skipped evaluation. Git/DuckDB are real; agent/evaluator are scripted.

This verifies commit scope, not whether compiler code is harmless.

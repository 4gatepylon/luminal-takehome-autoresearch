# Additional review findings

Written by Codex (GPT-6). Original review: commit `ac11873`.

All six findings across both review rounds now have targeted fixes. The linked
notes preserve the original behavior, reproduction, cause, and implemented change.

| Finding / description | Status | Current behavior |
| --- | --- | --- |
| [Score parsing](score_parsing_fix.md) | Implemented; original log-based fix superseded | `score.score()` returns full-precision metrics separately from logs; JSON is process transport. Library change: `3e5bbac`. |
| Cleanup/status (`cleanup_status_fix.md`) | Implemented | Select the next parent only after worktree cleanup succeeds; failures cannot promote proposals. Commit: `619d550`. |
| Hardcoded commit attribution | Implemented | Commit footers use the configured model/effort. Commit: `619d550`. |
| [Commit validation/hooks](commit_validation_fix.md) | Implemented | Runner commands bypass hooks. Before evaluation, require one compiler-only commit from the expected parent and a clean checkout. Manual Git behavior is unchanged. Commit: `bcca3d0`. |
| [Process cleanup](process_cleanup_fix.md) | Implemented | Kill remaining process-group children after success, error, timeout, or interruption; preserve results and exceptions. Commit: `46ab637`. |
| [Worktree creation](worktree_creation_fix.md) | Implemented | Guard creation, remove only this attempt's registration even if its directory is missing, preserve primary errors, and report secondary cleanup errors. |

Verification uses real temporary Git repositories, subprocesses, and DuckDB;
agent/evaluator output and failure points are scripted. See
[test boundaries](../tests/autoresearch/README.md).

Remaining limits: process cleanup does not contain deliberately detached
sessions; Git cleanup itself can still fail; crashes have no automatic recovery.
Scope checks and public correctness tests do not prove compiler code harmless.

# Testing

- Every test file must explicitly state what it tests in its module docstring or leading comment, and its filename must identify that scope. Use separate test files for different subjects or algorithms. Put compiler optimization tests in `tests/compiler_optimizations/`.
- Never assume an algorithm will stay the same: **the algorithm will ALWAYS change**. General correctness tests must check input/output behavior and required contracts without depending on an algorithm's incidental choices. To test a specific algorithm, call its specific implementation function directly and/or use an explicit forcing option that guarantees that implementation runs; do not rely on the compiler's default strategy.
- ALL commits by Codex must be denoted with: `Co-authored-by: Codex <noreply@openai.com>`. For other agents (such as Claude, Claude Code, Factory droids, Gemini, etc...) the same applies, but they should put their name and email (as applicable) instead.

# Documentation

- All documentation must describe the code as it is and its algorithmic, implementation, or design choices. Never reference PR discussions, conversations, or unrelated work history. READMEs must not reference planned or unimplemented features, work in progress, or pending PRs.
- Describe the resulting code, not the conversation that led to it. Never add "does not do X" merely because a user asked you to stop doing X and you changed the PR. For example, never write "Checks the machine contract and final memory, not heuristic address choices or scores." Write "Checks the machine contract and final memory."
- Never put specific numbers or values from a particular run's exact results in comments, docstrings, or documentation: algorithms and therefore their results WILL CHANGE. Describe the property being checked or the theoretical expectation, clearly labeled as such.

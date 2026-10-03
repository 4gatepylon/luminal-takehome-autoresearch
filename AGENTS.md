# Testing

- Every test file must explicitly state what it tests in its module docstring or leading comment, and its filename must identify that scope. Use separate test files for different subjects or algorithms. Put compiler optimization tests in `tests/compiler_optimizations/`.
- Never assume an algorithm will stay the same: **the algorithm will ALWAYS change**. General correctness tests must check input/output behavior and required contracts without depending on an algorithm's incidental choices. To test a specific algorithm, call its specific implementation function directly and/or use an explicit forcing option that guarantees that implementation runs; do not rely on the compiler's default strategy.

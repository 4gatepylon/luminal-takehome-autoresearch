- Keep code simple, direct, and easy to modify. Avoid unnecessary abstractions or
  performance optimizations; prefer a straightforward implementation.
- Name variables so readers know what they contain. For example,
  `data_predecessor_ids` instead of `data` when dealing with data predecessors
  and storing their integer IDs (instead of the full objects).
- Distinguish stable operation IDs from positions in a particular ordering. Use
  `_id` for an identifier and `_index` for a position; do not treat them as interchangeable.
- Name dictionaries using `x2y` to describe their key-to-value mapping, such as
  `op_id2prev_ops`. Make clear whether values are IDs, indices, objects, or collections.
- Use complete type annotations for function parameters, return values, and data
  structures, including local containers. Write `list[int]` or
  `dict[int, list[Operation]]` rather than bare `list` or `dict`. Give structured
  values a clear type definition that explains their fields and field types.
- Make inclusive and exclusive bounds explicit in names or documentation, using
  `_incl` and `_excl` when useful. For example, `np.random.randint(low_incl, high_excl)`
  includes the lower bound and excludes the upper bound.
- Use simple assertions where they clarify an important assumption, such as
  `assert all(type(op_id) is int for op_id in predecessor_ids)`.
- Do not add comments unless the user explicitly requests them. Use docstrings
  to define interfaces clearly and describe precisely and succinctly what each
  function or method does, including its inputs, outputs, and relevant assumptions.
- Assume the algorithm will change, so test correctness contracts rather than
  algorithmic implementation, unless requested by the user.
- Prefer dependency, resource-limit, execution, regression, and interface checks
  over exact scheduling or scratch choices.

# Testing

- Every test file must explicitly state what it tests in its module docstring or leading comment, and its filename must identify that scope. Use separate test files for different subjects or algorithms. Put compiler optimization tests in `tests/compiler_optimizations/`.
- Never assume an algorithm will stay the same: **the algorithm will ALWAYS change**. General correctness tests must check input/output behavior and required contracts without depending on an algorithm's incidental choices. To test a specific algorithm, call its specific implementation function directly and/or use an explicit forcing option that guarantees that implementation runs; do not rely on the compiler's default strategy.

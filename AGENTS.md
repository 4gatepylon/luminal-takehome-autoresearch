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

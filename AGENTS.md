- Keep code simple, direct, and easy to modify. Avoid unnecessary abstractions or
  performance optimizations; prefer a straightforward implementation.
- Name variables so readers know what they contain and how it is represented.
  Use `data_predecessor_ids`, `memory_predecessor_ids`, and `predecessor_ids` for
  lists of operation IDs; use `operations` or `predecessor_ops` for operation objects.
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
- Choose and document return values that are easy to use correctly. A latest
  predecessor index of `-1` means there is no predecessor, so legal earlier
  insertion indices are `[previous_index + 1, current_index)`. Check that the
  interval is nonempty before sampling.
- Use simple assertions where they clarify an important assumption, such as
  `assert all(type(op_id) is int for op_id in predecessor_ids)`.
- Explain non-obvious reasoning in comments. For example, no transitive dependency
  search is needed to find the latest prerequisite in a valid ordering because
  each indirect prerequisite precedes one of the direct prerequisites.
- Test enduring correctness contracts rather than freezing an algorithm that is
  expected to change. Prefer dependency, resource-limit, and execution checks over
  exact bundle layouts unless that layout is itself a required contract.

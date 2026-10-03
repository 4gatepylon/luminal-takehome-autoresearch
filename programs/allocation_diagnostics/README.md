# Allocation diagnostics

These seven programs isolate allocation tradeoffs while keeping the schedule fixed
across strategies. Each has two input cases, and all fit the original disjoint
allocator. They form the `allocation_diagnostics` scoring group; the eight supplied
programs remain in `original`, and `all` includes both groups.

Run each supported strategy and compare the per-program scratch column and group
aggregates:

```sh
python3 score.py
python3 score.py --strategy first-fit
python3 score.py --strategy disjoint
```

The hierarchical allocator is intentionally absent from this PR. Its subsequent
PR should add `hierarchical-first-fit` to the scoring flag's choices so the same
files can be compared with that option.

| Program | What it isolates |
| --- | --- |
| `01_alignment_holes.json` | An early long-lived scalar occupies address 0 in chronological first-fit, leaving an alignment hole before two overlapping vectors. A third vector reuses an earlier vector's storage. Vector-first placement can avoid the scalar-induced hole. |
| `02_vector_block_migration.json` | Eight scalars become live after the first vector dies but before the second dies. A later vector can use the second vector's block in chronological first-fit. Placing vectors first instead reserves both blocks during parts of each scalar's lifetime, forcing the scalars above them. This is a potential regression, not a favorable example. |
| `03_vector_lifetime_gaps.json` | Scalars live before, between, and after two nonoverlapping vector lifetimes. Both reuse strategies should be able to share those words across time. |
| `04_scalar_tail_reuse.json` | A vector stays live while three short-lived scalars appear sequentially. The scalars can share one word outside the vector's range. |
| `05_inclusive_boundary.json` | A vector and a scalar result both write at cycle 4, when the vector is also consumed. Their inclusive lifetimes overlap, so they cannot share words. |
| `06_retained_vectors_16.json` | Sixteen rounds load one vector and seven fresh scalars, consume the scalars, and read every vector loaded so far. All vectors stay live until the last round, while scalar locations can be reused each round. |
| `07_rolling_vectors_15_of_16.json` | The same sixteen rounds, but each reads only the newest fifteen vectors; the oldest vector dies before the sixteenth arrives. Scalars remain local to each round. |

The two extreme cases each use exactly 256 disjoint scratch words:
`16 * 8` for vector loads, `16 * 7` for scalar loads, and `16` scalar add results.
Each round adds its first and seventh scalar, stores that sum and the other five
scalars, then stores the retained vectors. These stores establish vector lifetimes
without extra vector arithmetic results, which would exceed the baseline limit.
The ideal reuse footprints are `16 * 8 + 7 = 135` and `15 * 8 + 7 = 127` words.

Reference measurements with the current scheduler (scratch words; smaller is better):

| Program | Disjoint | Chronological first-fit | Hierarchical first-fit from PR #33 |
| --- | ---: | ---: | ---: |
| Alignment holes | 25 | 24 | 17 |
| Vector block migration | 32 | 16 | 24 |
| Vector lifetime gaps | 19 | 8 | 8 |
| Scalar tail reuse | 11 | 9 | 9 |
| Inclusive boundary | 10 | 9 | 9 |
| Sixteen retained vectors | 256 | 136 | 135 |
| Latest fifteen of sixteen vectors | 256 | 128 | 127 |

The hierarchical column was measured separately using the allocator from
[PR #33](https://github.com/4gatepylon/luminal-takehome-autoresearch/pull/33), without
adding its implementation to this branch. These are diagnostic observations,
not assertions that future algorithms must produce the same addresses or scores.
The group contains wins, a regression, and ties; its aggregate is not a prediction
of performance on unseen workloads.

# Group: `allocation_diagnostics`

These programs are meant to showcase the benefits of hierarchical allocation over default first-fit allocation.

```sh
python3 score.py
python3 score.py --allocation-strategy first-fit
python3 score.py --allocation-strategy disjoint
```

| Program | What it isolates |
| --- | --- |
| `01_alignment_holes.json` | An early long-lived scalar occupies address 0 in chronological first-fit, leaving an alignment hole before two overlapping vectors. A third vector reuses an earlier vector's storage. |
| `02_vector_block_migration.json` | Eight scalars become live after the first vector dies but before the second dies. A later vector uses the second vector's block in chronological first-fit. |
| `03_vector_lifetime_gaps.json` | Scalars live before, between, and after two nonoverlapping vector lifetimes. Chronological first-fit shares those words across time. |
| `04_scalar_tail_reuse.json` | A vector stays live while three short-lived scalars appear sequentially. The scalars can share one word outside the vector's range. |
| `05_inclusive_boundary.json` | A vector and a scalar result both write at cycle 4, when the vector is also consumed. Their inclusive lifetimes overlap, so they cannot share words. |
| `06_retained_vectors_16.json` | Sixteen rounds load one vector and seven fresh scalars, consume the scalars, and read every vector loaded so far. All vectors stay live until the last round, while scalar locations can be reused each round. |
| `07_rolling_vectors_15_of_16.json` | The same sixteen rounds, but each reads only the newest fifteen vectors; the oldest vector dies before the sixteenth arrives. Scalars remain local to each round. |
| `08_pinned_vector_blocks.json` | Sixteen vectors die in reverse order, each replaced by a scalar that stays live through fourteen new vectors. Chronological first-fit leaves one scalar in each aligned block, preventing vector reuse despite seven free words per block. |

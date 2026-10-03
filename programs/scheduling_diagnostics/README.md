# Scheduling diagnostics

These programs isolate ordering choices in the latency-constrained operation DAG.

| Program | Scheduling structure |
| --- | --- |
| `01_shared_roots_fanout.json` | Shared vector operands feed a terminal branch and a sibling join. Draining the terminal branch reduces overlapping results. |
| `02_shared_value_branches.json` | An intermediate vector feeds an early output and a later join. Branch overlap trades execution time against scratch usage. |
| `03_mixed_width_overlap.json` | A scalar sum expands into a vector beside an independent vector chain. Their overlap trades execution time against scratch usage. |
| `04_partial_overlap_barrier.json` | A scalar write separates two overlapping vector reads. Legal reordering preserves the before/after memory relationship. |

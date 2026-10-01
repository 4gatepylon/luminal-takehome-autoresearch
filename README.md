# Luminal Compiler Take Home

This take-home exercise is for candidates joining the compiler engineering team
at Luminal. It evaluates instruction scheduling, scratch allocation, correctness,
and engineering judgment when building a compiler backend.

Build a general backend compiler for a small, deterministic VLIW machine. The
input is a typed, straight-line SSA program. Your compiler must assign every
virtual value to the machine's scratchpad and schedule every operation into
VLIW bundles. Correctness is required; shorter schedules and smaller scratch footprints score better.

The starter compiler is deliberately simple and serial. It is correct for all
supported programs, so you can improve it incrementally and measure every
change.

## Candidate task

Implement scheduling and scratch allocation in `compile_program()` in `work/compiler.py`.
You may add helpers and standard-library imports to that file. Do not modify `machine.py`, the
public programs, or the tests when preparing a submission.

Your compiler receives a parsed program dictionary and returns:

```python
{
    "scratch": {"virtual_value": 0, "another_value": 8},
    "bundles": [
        {"load": [0, 1]},
        {},
        {"vector": [2], "store": [3]},
    ],
}
```

The `scratch` mapping assigns each SSA result to a word address in scratch.
The lists in each bundle contain operation IDs from the input program. Missing
engines and empty bundles are allowed. Every operation must appear exactly
once.

Run the public suite and benchmark with:

```sh
make test   # unit tests
make score  # public benchmark
make eval   # tests, then score only if tests pass
```

The same functions are available from Python:

```python
from evaluate import test, score, eval

metrics = eval()  # runs tests, then scores; returns None if tests fail
```

`test()` returns a `unittest.TestResult` with `.wasSuccessful()` and accepts
`verbosity` and `stream` options for its output. `score()` returns a dictionary
with `cycle_speedup`, `scratch_reduction`, and `combined_score` without printing.
Pass `verbose=True` to `score()` or `eval()` to print the benchmark report.
The CLI returns a nonzero exit status when tests fail.

All three functions accept `compiler_filepath`, defaulting to `work/compiler.py`;
the CLI accepts `--compiler-filepath <path>`. Evaluation requires macOS:
`sandbox.py` runs each compiler's JSON CLI with a 20-second timeout, blocking
writes, networking, forks, and signals to other processes. The parent checks the
returned schedule with the trusted machine and computes scores. Invoke from the
repository root with `PYTHONPATH="$PWD"` so candidates can import `machine`.

Install the development tools, automatically fix lint issues, and format all Python files with:

```sh
python3 -m pip install -r requirements.txt
make format
```

Compile one program to a JSON schedule with:

```sh
python3 -m work.compiler programs/03_vector_axpy.json > axpy.schedule.json
python3 machine.py programs/03_vector_axpy.json axpy.schedule.json
```

Public programs are in `programs/`. Submission grading uses another
eight programs that are not included in the candidate repository. Hidden
programs use only the documented operations and limits below. Solutions that
special-case public filenames, operation IDs, or constants will not generalize.

## Machine model

The machine has a 256-word scratchpad. Each word is an unsigned 32-bit integer.
There is no implicit register file or cache. Every SSA result must be assigned
scratch space before it can be consumed.

SIMD vectors contain eight words and occupy eight consecutive scratch words.
Vector allocations must begin at an address divisible by eight. Scalar values
occupy one word. Values may share all or part of their scratch ranges when their
live intervals do not overlap. All supplied programs fit without spilling even
with the starter's allocation; reducing scratch use is part of the challenge.

A value's live interval starts when its result writes scratch, at issue cycle
plus latency, and ends at its last consumer's issue cycle, inclusive. An unused
result still occupies scratch for its write cycle. Writes happen before reads in
a cycle, so a new result must write strictly after an old value's final read to
reuse its words. Two writes to overlapping words in the same cycle are invalid.
An operation may read its input and later write its output to the same address.
Account for in-flight results when choosing addresses and schedules.

Scratch footprint is the highest allocated end address, including alignment
holes. For example, a vector at address 8 uses a footprint of at least 16 words.
There are no moves or spills to insert: every original operation must issue
exactly once, and the input program must not be changed.

Each cycle issues one VLIW bundle with these engine limits:

| Engine | Slots per cycle |
| --- | ---: |
| `load` | 2 |
| `scalar` | 2 |
| `vector` | 2 |
| `store` | 1 |
| `flow` | 1 |

An operation issued in cycle `c` may be consumed in cycle `c + latency`.
Results are not forwarded within the same bundle. Independent operations can
issue in any order if dependencies, engine capacity, and memory ordering are
preserved.

## Instruction set

| Operation | Engine | Latency | Result | Arguments |
| --- | --- | ---: | --- | --- |
| `const` | load | 1 | scalar | immediate `value` field |
| `load` | load | 3 | scalar | memory `buffer` and `offset` |
| `vload` | load | 4 | vector | eight words at `buffer` and `offset` |
| `store` | store | 1 | none | scalar value, memory `buffer` and `offset` |
| `vstore` | store | 1 | none | vector value, memory `buffer` and `offset` |
| `add`, `sub`, `xor`, `and`, `or`, `shl`, `shr`, `eq`, `lt` | scalar | 1 | scalar | two scalars |
| `mul` | scalar | 2 | scalar | two scalars |
| `vadd`, `vsub`, `vxor`, `vand`, `vor`, `vshl`, `vshr` | vector | 1 | vector | two vectors, lane-wise |
| `vmul` | vector | 3 | vector | two vectors, lane-wise |
| `splat` | vector | 1 | vector | one scalar copied to every lane |
| `select` | flow | 1 | scalar | condition, true value, false value |
| `vselect` | flow | 2 | vector | vector condition, true vector, false vector |

Arithmetic wraps modulo `2**32`. Shift counts use their low five bits. `eq`
and `lt` produce `0` or `1`; comparisons are unsigned. `select` chooses its
second argument when the condition is nonzero.

Programs use the following JSON shape:

```json
{
  "name": "example",
  "buffers": {"x": 8, "out": 8},
  "operations": [
    {"id": 0, "op": "vload", "dest": "vx", "buffer": "x", "offset": 0},
    {"id": 1, "op": "vstore", "args": ["vx"], "buffer": "out", "offset": 0}
  ],
  "cases": [
    {"x": [1, 2, 3, 4, 5, 6, 7, 8], "out": [0, 0, 0, 0, 0, 0, 0, 0]}
  ]
}
```

Operations are listed in SSA dependency order. IDs are consecutive starting at
zero. Every argument names a result defined by an earlier operation.

## Memory ordering

Memory ranges are known statically. Loads may reorder freely unless they overlap
an earlier store. A store must remain after every earlier overlapping load or
store, and every later overlapping load or store must remain after it. Two
ordered memory operations must issue in different cycles. Operations accessing
provably disjoint ranges may reorder.

## Program descriptions

The public programs below cover scalar and vector dependency chains, memory
traffic, and inputs for optimization experiments. All arithmetic wraps modulo
`2**32`.

| Program | Description |
| --- | --- |
| [01_scalar_pipeline.json](programs/01_scalar_pipeline.json) | A scalar multiply-add feeds bitwise mixing, shifts, a comparison, and a final selection. Exercises scheduling along a dependency chain. |
| [02_scalar_dual_chain.json](programs/02_scalar_dual_chain.json) | Two scalar products share an `a + c` intermediate, producing `a * b + (a + c)` and `(c * d) ^ (a + c)`. Exposes parallel work and shared dependencies. |
| [03_vector_axpy.json](programs/03_vector_axpy.json) | Computes `3 * x + y` over 16 elements using two eight-lane vector paths and a broadcast scalar constant. |
| [04_vector_bitmix.json](programs/04_vector_bitmix.json) | XORs 16 data elements with masks, shifts each result left by five bits, and adds the original data. Exercises parallel vector chains. |
| [05_mixed_broadcast.json](programs/05_mixed_broadcast.json) | Broadcasts scalar gate and bias values to compute `weights * gate + bias` over eight lanes. Connects scalar loads to vector arithmetic. |
| [06_parallel_memory.json](programs/06_parallel_memory.json) | Computes `out0 = (a + b) * (c - d)` and `out1 = out0 ^ a` over 16 elements. Exercises independent loads, vector arithmetic, and multiple stores. |
| [07_scalar_selects.json](programs/07_scalar_selects.json) | Computes the unsigned maximum of each of four score/threshold pairs using comparisons and selections. Exercises the flow engine. |
| [08_vector_reduction.json](programs/08_vector_reduction.json) | Sums eight vectors lane by lane through a balanced addition tree, then XORs the result with a broadcast constant. Exercises dependencies that converge on one output vector. |
| [09_dead_code.json](programs/09_dead_code.json) | Stores `x + y * z` while operations 5–16 compute unused expressions: `x + y * 2`, `x * z + y`, `x * y * z`, and `x + z * z + y * x * x`. Provides input for dead-code elimination. |
| [10_repeated_addition.json](programs/10_repeated_addition.json) | Adds 16 copies of `x` in a left-associated chain of 15 additions. Provides input for simplification to `16 * x` or a balanced addition tree. Cases include zero, one, ordinary values, and overflow. |
| [11_repeated_multiplication.json](programs/11_repeated_multiplication.json) | Multiplies 16 copies of `x` in a left-associated chain of 15 multiplications. Provides input for repeated squaring to compute `x**16`. Cases include zero, one, ordinary values, and overflow. |
| [12_algebraic_associativity.json](programs/12_algebraic_associativity.json) | Computes `out1 = x * z + y * z` and `out2 = x * z + y * z + 2 * x * z`, with separate product nodes for each output followed by additions; the last term is `(2 * x) * z`. Provides input for reassociation and distributive factoring into `(x + y) * z` and `(3 * x + y) * z`. |

Programs 09–12 expose opportunities for dead-code elimination and algebraic
simplification. The current schedule-only grader requires every original
operation to issue exactly once and preserves its dependencies. Accepting
eliminated operations or rewritten expressions requires changes to the
compiler/grader contract.

## Evaluation

Every public and hidden case is interpreted directly from the input IR to
produce its reference memory image. The frozen grader then validates scratch
allocations, dependencies, engine limits, latencies, memory ordering, and final
memory. Modifying or bypassing the public simulator cannot change hidden results.

Correctness on all programs is the first requirement. Among correct compilers,
we report geometric-mean cycle speedup and geometric-mean scratch reduction
relative to the frozen serial baseline across all public and hidden programs. For each
program these ratios are `baseline_cycles / cycles` and
`baseline_scratch_words / scratch_words`. The combined score is
`sqrt(cycle_speedup_geomean * scratch_reduction_geomean)`, giving equal weight
to both objectives. The starter scores 1.000x on each metric. Public scoring
uses the same formula on the visible programs; the private grader reports
the final combined result on all public and hidden programs. We also review compiler structure, clarity, and the
tradeoffs in your scheduling heuristic.

Useful directions include critical-path priorities, latency-aware ready queues,
scarce-engine prioritization, and filling bundles without blocking newly ready
work. Optimal scheduling is not expected.


## Logistics and submission

Use Python 3.10 or later; no third-party packages are required. Run commands
from the repository root. Spend up to four hours, including reading and testing;
submit what you have at that point and note unfinished work. We value a clear,
correct incremental improvement over an unfinished complicated design.

Documentation, internet research, and AI coding tools are allowed. Disclose the
tools used and how you checked their output. You should be able to explain and
modify your submission in a follow-up discussion. Do not share the exercise or
solution publicly or collaborate with another person.

Email `work/compiler.py` and a short `SUBMISSION.md` to
[submissions@luminal.com](mailto:submissions@luminal.com). Include time spent,
your scheduling and allocation approach, measured public scores, tradeoffs, unfinished work, and
any tool assistance. You may include additional tests separately; do not alter
the supplied tests or machine. The compiler must emit only schedule JSON on
stdout when invoked through the documented CLI; send diagnostics to stderr.
The grader allows 20 seconds per program. Hidden inputs follow the same machine
contract, and grading uses trusted copies of all public and hidden programs.

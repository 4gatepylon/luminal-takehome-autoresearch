# Readable SSA programs (`.ssa`)

`program_ssa.py` converts existing program JSON to readable SSA and back. It
never executes, optimizes, schedules, or rewrites the program. Existing compiler
and machine entry points continue to consume JSON; convert edited SSA back to
JSON before using them.

## File layout

```text
lang: ssa-v1
name: "example"

================ BUFFERS ================
{"a":8}
{"out":8}

================ PROGRAM ================
# Load eight words, then multiply each lane by three.
values = buff[a][0:8]
factor = const(3)
factors = ...factor
scaled = values * factors
buff[out][0:8] = scaled

================ CASES ================
{"a":[1,2,3,4,5,6,7,8],"out":[0,0,0,0,0,0,0,0]}
```

The final dash in `ssa-v1` separates the language name (`ssa`) from its version
(`v1`). Version 1 is the only supported version. The `name` is a JSON string
and preserves the original program name.

All three section markers are mandatory, occur exactly once, occupy their own
lines, and appear in the order shown. Leading/trailing whitespace is allowed.
Buffers are JSONL with one single-entry object per buffer. Cases are JSONL with
one complete case object per line. Cases use the original JSON buffer names,
including when the program uses aliases.

Blank lines and lines whose first non-whitespace character is `#` are ignored
in every section. Inline comments are unsupported. A `#` inside a JSON string
is string data. Within the program, all whitespace, including newlines, is
equivalent: statements can span lines or share a line. JSONL objects and header
values must stay on a single physical line.

## Operations

Every statement describes exactly one original operation. IDs are assigned in
statement order, starting at zero. Every value is defined once, before use.
There are no nested expressions, implicit constants, copies, or broadcasts.

| Operation | Syntax |
| --- | --- |
| Integer constant | `a = const(-3)` |
| Scalar load | `a = buff[input][0]` |
| Vector load | `v = buff[input][0:8]` |
| Scalar store | `buff[out][0] = a` |
| Vector store | `buff[out][8:16] = v` |
| Arithmetic | `r = a + b`, `r = a - b`, `r = a * b` |
| Bitwise | `r = a ^ b`, `r = a & b`, `r = a \| b` |
| Shifts | `r = a << b`, `r = a >> b` |
| Scalar comparisons | `r = a == b`, `r = a < b` |
| Splat | `v = ...a` |
| Select | `r = yes if { condition } else no` |

Vector slices have an exclusive end and span exactly eight words. Types follow
from prior definitions: vector operands select vector arithmetic opcodes. Both
operands must have the same type; vector comparisons are unsupported by the
machine. Integers are written in decimal, with an optional minus sign. Exact
constant values are preserved; machine arithmetic still wraps to 32 bits.

Splat repeats one scalar across all eight lanes. Selection chooses `yes` for a
nonzero condition and `no` for zero. All three selection operands must be
previously defined variables of the same type. Vector selection chooses per
lane. Both alternatives are already computed; this is not conditional execution.

Names must satisfy Python's `str.isidentifier()` and cannot be Python keywords
or the reserved names `buff` and `const`. This excludes braces, dots, whitespace,
and therefore triple dots. Unicode identifiers are supported and retained
exactly, without Unicode normalization.

## Lossless conversion

For supported program JSON data, the codec guarantees:

```python
parse_program(format_program(program)) == program
```

It preserves all fields and values, operation/case order, names, buffer sizes,
and the distinction between omitted and explicit empty argument lists. JSON
indentation, object-key order, and numeric spelling are not part of this
guarantee. SSA comments and custom whitespace do not survive conversion through
JSON. Formatting is deterministic and produces a trailing newline.

Extra top-level fields use an optional `metadata` header. Extra operation fields
use an optional `@` JSON object after the statement:

```text
metadata: {"description":"example"}
```

```text
a = const(3) @ {"args":[],"note":"keep this field"}
```

Metadata cannot override fields already expressed by the syntax. Duplicate JSON
keys, non-JSON numbers such as `NaN`, and invalid programs are rejected.

The original JSON format allows arbitrary non-empty names. When a name is not a
valid SSA identifier, the formatter assigns a collision-free alias and records
its original spelling in the optional header:

```text
aliases: {"buffers":{"buffer_0":"input data"},"values":{"value_0":"original...name"}}
```

Only actual names/references are restored through this mapping; unrelated
metadata strings remain untouched. Alias collisions and unused aliases are
errors. Ordinary programs need no aliases or metadata headers.

Section markers are reserved literal strings. If any JSON string contains a
marker, the formatter encodes its equals signs as `\u003d`, preserving the
decoded string while ensuring each literal marker appears only once in the
file. Manually authored string data must follow the same rule.

## CLI and Python API

Run from the repository root with Python 3.10+:

```sh
export PYTHONPATH="$PWD"
python3 -B program_ssa.py to-ssa programs/03_vector_axpy.json -o example.ssa
python3 -B program_ssa.py to-json example.ssa -o example.json
```

Omit `-o` to emit the converted file to stdout. SSA input/output file paths must
end in `.ssa`. Parse and validation errors go to stderr, return exit code 1,
and include source-line context where available. Conversion finishes before
the output file is opened, so invalid input does not overwrite existing output.

### Regenerating all companions

```sh
PYTHONPATH="$PWD" python3 -B program_ssa.py regenerate
PYTHONPATH="$PWD" python3 -B program_ssa.py regenerate --clobber
# An optional directory replaces the default programs/ search root:
PYTHONPATH="$PWD" python3 -B program_ssa.py regenerate path/to/programs --clobber
```

The command searches recursively for `.json` programs and generates companions
beside them. Existing files are compared byte-for-byte with canonical generated
SSA, including whitespace, comments, and line endings. Matching files are never
rewritten, and an entirely up-to-date directory exits successfully without writes.
Without `--clobber`, a differing file produces an error with its path and leaves
the entire batch untouched. With `--clobber`, differing files are replaced.
Missing companions are created in either mode, after all input programs and
existing outputs have been checked. Invalid input, an empty directory, or a
missing directory is an error. Preflight failures cause no writes; filesystem
errors during writing can leave earlier files in the batch written.

```python
from program_ssa import format_program, parse_program

source = format_program(program)
restored = parse_program(source)
assert restored == program
```

## Verification

```sh
PYTHONPATH="$PWD" make test-ssa
PYTHONPATH="$PWD" make test
npm ci --prefix vscode/ssa
make test-ssa-highlighting
```

The Python tests are grouped into round trips, authoring, validation, and CLI
behavior. They discover every JSON file beneath `programs/`, assert complete
JSON → SSA → JSON equality, and verify its checked-in `.ssa` counterpart. They
also cover every opcode, canonical formatting, multiline statements, edits,
comments, aliases, escaping, metadata, invalid input, and scalar/vector
selection semantics. The original JSON fixtures are unchanged.

`evaluate.py` also checks each JSON program's `.ssa` equivalent before running
the compiler in `test`, `score`, or `eval`. Missing files, malformed SSA, or any
decoded data mismatch fail evaluation, including for programs whose compiler
failure is expected. This comparison covers the full program, including cases
and metadata; SSA whitespace and comments do not affect it. Evaluation does not
regenerate or repair files automatically. After changing a JSON fixture, use
`regenerate --clobber` to update its companions, or `to-ssa` for a single file.
Integration tests cover each entry point
and verify that failed checks prevent compiler execution.

The highlighting tests use VS Code's TextMate tokenizer and Oniguruma engine to
check every `.ssa` example, syntax scopes, nested JSON metadata, and section
transitions. The extension and its installation instructions are in
[`vscode/ssa`](../vscode/ssa/README.md).

"""File conversion and safe batch regeneration through public representations."""

import argparse
from pathlib import Path
import sys

from program.representations.json import JsonRepresentation
from program.representations.ssa import SsaRepresentation


def regenerate_programs(directory: Path, *, clobber: bool = False) -> tuple[int, int]:
    """Check companions, or repair with clobber; always reject unaccounted files."""
    json_directory = directory / "json"
    ssa_directory = directory / "ssa"
    if not json_directory.is_dir():
        raise ValueError(f"not a program JSON directory: {json_directory}")
    paths = sorted(path for path in json_directory.rglob("*.json") if path.is_file())
    expected = {ssa_directory / path.relative_to(json_directory).with_suffix(".ssa") for path in paths}
    existing = {path for path in ssa_directory.rglob("*") if path.is_file() or path.is_symlink()}
    unaccounted = existing - expected
    if unaccounted:
        raise ValueError("unaccounted files without matching JSON: " + ", ".join(str(path) for path in sorted(unaccounted)))
    if not paths:
        raise ValueError(f"no JSON programs found in {json_directory}")

    pending: list[tuple[Path, bytes]] = []
    unchanged = 0
    for path in paths:
        try:
            program = JsonRepresentation().decode(path.read_text(encoding="utf-8"))
            source = SsaRepresentation().encode(program).encode("utf-8")
            output = ssa_directory / path.relative_to(json_directory).with_suffix(".ssa")
            if output.exists() or output.is_symlink():
                if output.read_bytes() == source:
                    unchanged += 1
                    continue
                if not clobber:
                    raise ValueError(f"{output} exists and differs from generated SSA; rerun with --clobber to overwrite")
            elif not clobber:
                raise ValueError(f"{output} is missing; rerun with --clobber to generate")
            pending.append((output, source))
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ValueError(f"{path}: {error}") from error

    # Validate the entire batch before writing, including when clobbering.
    for output, source in pending:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as handle:
            handle.write(source)
    return len(pending), unchanged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, alias in (("json2ssa", "to-ssa"), ("ssa2json", "to-json")):
        convert = commands.add_parser(command, aliases=[alias], help="convert a file" + (" or all JSON programs" if command == "json2ssa" else ""))
        convert.set_defaults(command=command)
        convert.add_argument("input", type=Path)
        convert.add_argument("-o", "--output", type=Path, help="output file (default: stdout); SSA files must end in .ssa")
        if command == "json2ssa":
            convert.add_argument(
                "--programs-root", type=Path, default=Path("programs"), help="root containing json/ and ssa/ for 'all' (default: programs)"
            )
            convert.add_argument(
                "--clobber", action="store_true", help="with 'all', generate missing or changed SSA; unaccounted files remain errors"
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "json2ssa" and args.input == Path("all"):
            if args.output:
                raise ValueError("--output is only supported for single-file conversions")
            written, unchanged = regenerate_programs(args.programs_root, clobber=args.clobber)
            print(f"Wrote {written} SSA file(s); {unchanged} already up to date.")
            return 0
        if args.command == "json2ssa" and args.output and args.output.suffix != ".ssa":
            raise ValueError("SSA output files must end in .ssa")
        if args.command == "ssa2json" and args.input.suffix != ".ssa":
            raise ValueError("SSA input files must end in .ssa")
        source = args.input.read_text(encoding="utf-8")
        if args.command == "json2ssa":
            output = SsaRepresentation().encode(JsonRepresentation().decode(source))
        else:
            output = JsonRepresentation().encode(SsaRepresentation().decode(source))
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"{args.input}: {error}", file=sys.stderr)
        return 1
    return 0

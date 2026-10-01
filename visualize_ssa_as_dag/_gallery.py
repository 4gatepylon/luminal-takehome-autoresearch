"""Generate an offline gallery and its diagram assets."""

from html import escape
from pathlib import Path
from string import Template
import subprocess
from urllib.parse import quote

from machine import load_program
from visualize_ssa_as_dag._dot import program_dot
from visualize_ssa_as_dag._graphviz import render_svg


_ASSETS = Path(__file__).parent / "_assets"


def _card(path: Path, program: dict, index: int) -> str:
    name = escape(program["name"])
    filename = escape(path.name)
    asset = escape(quote(path.stem, safe=""), quote=True)
    operations = program["operations"]
    values = sum("dest" in operation for operation in operations)
    return f"""<a class="card" href="pages/{asset}.html" aria-label="Open {filename} diagram">
  <header class="card-heading">
    <span class="number">{index:02d}</span>
    <div><h2>{filename}</h2><p class="filename">{name}</p></div>
  </header>
  <div class="preview">
    <img src="diagrams/{asset}.svg" alt="SSA dataflow for {name}" loading="lazy">
  </div>
  <footer><span>{len(operations)} operations · {values} values</span>
    <span class="links">View diagram →</span>
  </footer>
</a>"""


def write_gallery(
    programs_dir: Path, output_dir: Path, *, clobber: bool = False
) -> Path:
    """Render every JSON program in filename order and return the index path.

    All links are relative; the generated directory works over file:// without
    a server or network access. Existing nonempty directories require clobber;
    regeneration replaces matching assets but leaves unrelated files alone.
    """
    if output_dir.exists():
        if not output_dir.is_dir():
            raise ValueError(f"gallery output is not a directory: {output_dir}")
        if any(output_dir.iterdir()) and not clobber:
            raise ValueError(
                f"gallery output already exists: {output_dir}; "
                "use --clobber (or --c) to overwrite it"
            )
    if not programs_dir.is_dir():
        raise ValueError(f"program directory does not exist: {programs_dir}")
    paths = sorted(programs_dir.glob("*.json"))
    if not paths:
        raise ValueError(f"no JSON programs found in {programs_dir}")
    diagrams = output_dir / "diagrams"
    diagrams.mkdir(parents=True, exist_ok=True)
    pages = output_dir / "pages"
    pages.mkdir(exist_ok=True)
    detail_template = Template((_ASSETS / "diagram.html").read_text(encoding="utf-8"))
    cards = []
    for index, path in enumerate(paths, start=1):
        try:
            program = load_program(path)
            source = program_dot(program)
            svg = render_svg(source)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ValueError(f"could not render {path.name}: {exc}") from exc
        (diagrams / f"{path.stem}.svg").write_text(svg, encoding="utf-8")
        (diagrams / f"{path.stem}.dot").write_text(source, encoding="utf-8")
        detail = detail_template.substitute(
            filename=escape(path.name),
            name=escape(program["name"]),
            asset=escape(quote(path.stem, safe=""), quote=True),
        )
        (pages / f"{path.stem}.html").write_text(detail, encoding="utf-8")
        cards.append(_card(path, program, index))

    for filename in ("gallery.css", "gallery.js"):
        (output_dir / filename).write_bytes((_ASSETS / filename).read_bytes())
    template = Template((_ASSETS / "gallery.html").read_text(encoding="utf-8"))
    page = template.substitute(count=len(paths), cards="\n".join(cards))
    output = output_dir / "index.html"
    output.write_text(page, encoding="utf-8")
    return output

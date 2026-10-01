"""Internal Graphviz process adapter."""

import shutil
import subprocess


def render_svg(source: str) -> str:
    """Render DOT using the installed Graphviz executable within 30 seconds."""
    dot = shutil.which("dot")
    if dot is None:
        raise ValueError(
            "Graphviz is required: on macOS, brew install graphviz "
            "(or use -o graph.dot)"
        )
    return subprocess.run(
        [dot, "-Tsvg"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout

"""Implemented by Codex (GPT-6).

Click entry point; CLI values override the hydrated YAML configuration."""

from pathlib import Path
import shutil
import subprocess
from typing import get_args

import click
from ruamel.yaml.error import YAMLError

from .config import Effort, config_yaml, load_config


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", "config_path", type=click.Path(
    exists=True, dir_okay=False, readable=True, path_type=Path,
), help="Partial YAML config; omitted values use packaged defaults.")
@click.option("--iterations", type=click.IntRange(min=0),
              help="Number of agent attempts; 0 evaluates only the baseline.")
@click.option("--base", help="Starting branch or commit.")
@click.option("--db", type=click.Path(dir_okay=False, path_type=Path),
              help="DuckDB file; relative paths start at the repository root.")
@click.option("--model", help="Codex model.")
@click.option("--effort", type=click.Choice(get_args(Effort)), help="Reasoning effort.")
@click.option("--codex-timeout", type=click.FloatRange(min=0, min_open=True),
              help="Seconds allowed per agent attempt.")
@click.option("--eval-timeout", type=click.FloatRange(min=0, min_open=True),
              help="Seconds allowed per evaluation command.")
@click.option("--show-config", is_flag=True,
              help="Print validated, hydrated YAML and exit without running anything.")
def main(config_path: Path | None, show_config: bool, **overrides) -> None:
    """Run sequential compiler experiments in disposable worktrees.

    Precedence: packaged defaults < --config YAML < explicit CLI options.
    """
    try:
        config = load_config(config_path, overrides=overrides)
    except (OSError, ValueError, YAMLError) as exc:
        raise click.ClickException(f"Invalid configuration: {exc}") from exc
    if show_config:
        click.echo(config_yaml(config), nl=False)
        return
    if not shutil.which("codex"):
        raise click.ClickException(
            "Install the Codex CLI and run codex login first (see autoresearch/README.md)."
        )

    # Help and config inspection need neither a Git checkout nor database imports.
    from sqlalchemy.exc import SQLAlchemyError
    from .environment import GitRepository
    from .runner import research

    try:
        repo = GitRepository.discover(Path.cwd()).root
        research(config, repo)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException((exc.stderr or str(exc)).strip()) from exc
    except (OSError, RuntimeError, SQLAlchemyError) as exc:
        raise click.ClickException(str(exc)) from exc

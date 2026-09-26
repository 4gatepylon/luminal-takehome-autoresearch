"""Validated YAML configuration; defaults live only in defaults.yaml."""

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, RootModel
from pydantic.dataclasses import dataclass
from pydantic_yaml import parse_yaml_file_as, to_yaml_str


DEFAULT_CONFIG = Path(__file__).with_name("defaults.yaml")
Effort = Literal["low", "medium", "high", "xhigh"]


@dataclass(frozen=True, config=ConfigDict(extra="forbid", allow_inf_nan=False,
                                        str_strip_whitespace=True))
class ResearchConfig:
    """Configuration for one sequential run; DB paths are repository-relative."""

    iterations: Annotated[int, Field(ge=0, strict=True)]
    base: Annotated[str, Field(min_length=1)]
    db: Path
    model: Annotated[str, Field(min_length=1)]
    effort: Effort
    codex_timeout: Annotated[float, Field(gt=0, strict=True)]
    eval_timeout: Annotated[float, Field(gt=0, strict=True)]


def load_config(path: Path | None = None, *,
                overrides: dict[str, Any] | None = None) -> ResearchConfig:
    """Merge packaged defaults < optional YAML < explicitly supplied CLI values."""
    values = parse_yaml_file_as(dict[str, Any], DEFAULT_CONFIG)
    if path is not None:
        values.update(parse_yaml_file_as(dict[str, Any] | None, path) or {})
    if overrides:
        values.update({key: value for key, value in overrides.items() if value is not None})
    return ResearchConfig(**values)


def config_yaml(config: ResearchConfig) -> str:
    """Render hydrated settings as reusable YAML, including Path values."""
    return to_yaml_str(RootModel[ResearchConfig](config))

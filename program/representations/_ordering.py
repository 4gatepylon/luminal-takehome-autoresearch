"""Stable dictionary ordering shared by the text encoders."""

from typing import Any


def sort_mapping_keys(value: Any) -> Any:
    """Copy nested dictionaries in key order, preserving all list ordering."""
    if isinstance(value, dict):
        return {key: sort_mapping_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [sort_mapping_keys(item) for item in value]
    return value

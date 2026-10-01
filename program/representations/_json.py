"""Strict JSON syntax shared by JSON programs and embedded SSA metadata."""

import json


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"{value} is not a JSON value")


DECODER = json.JSONDecoder(object_pairs_hook=_object, parse_constant=_invalid_constant)

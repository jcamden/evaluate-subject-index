"""Shared JSON Schema validation for current evaluation artifacts."""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "references" / "schemas"


def _decimal_numbers(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _decimal_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimal_numbers(item) for item in value]
    return value


@lru_cache(maxsize=1)
def _schema_store() -> dict[str, dict[str, Any]]:
    store: dict[str, dict[str, Any]] = {}
    for path in SCHEMA_ROOT.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        store[path.name] = document
        store[path.resolve().as_uri()] = document
    return store


def schema_errors(document: Any, schema_name: str) -> list[str]:
    """Return deterministic, path-qualified structural errors."""
    schema_path = SCHEMA_ROOT / schema_name
    schema = _schema_store()[schema_name]
    resolver = jsonschema.RefResolver(
        base_uri=schema_path.resolve().as_uri(),
        referrer=schema,
        store=_schema_store(),
    )
    errors = sorted(
        jsonschema.Draft202012Validator(schema, resolver=resolver).iter_errors(
            _decimal_numbers(document)
        ),
        key=lambda item: [str(part) for part in item.absolute_path],
    )
    return [
        f"{'.'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in errors
    ]

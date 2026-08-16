"""YAML representation adapter.

PyYAML is optional and isolated to this module. Importing `openams.metadata`
does not require PyYAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .errors import InputError, SerializationDependencyError


def load_yaml_mapping(path: str | Path) -> Mapping[str, Any]:
    """Load one YAML document whose root must be a mapping."""

    try:
        import yaml
    except ImportError as exc:
        raise SerializationDependencyError(
            "PyYAML is required only for YAML input; install it with "
            "'python -m pip install PyYAML' or provide already-parsed mappings"
        ) from exc

    source = Path(path).expanduser()
    if not source.is_file():
        raise InputError(f"YAML input does not exist or is not a file: {source}")

    try:
        with source.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
    except OSError as exc:
        raise InputError(f"cannot read YAML input: {source}") from exc
    except yaml.YAMLError as exc:
        raise InputError(f"invalid YAML in {source}: {exc}") from exc

    if value is None:
        raise InputError(f"YAML document is empty: {source}")
    if not isinstance(value, dict):
        raise InputError(f"YAML root must be a mapping: {source}")
    return value

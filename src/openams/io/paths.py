"""Filesystem path objects and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import InputError


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Filesystem references used by an OpenAMS application entry point."""

    netlist: Path
    specifications: Path
    design_intent: Path
    design_rules: Path
    simulation: Path

    def __post_init__(self) -> None:
        for name in (
            "netlist",
            "specifications",
            "design_intent",
            "design_rules",
            "simulation",
        ):
            value = Path(getattr(self, name)).expanduser()
            object.__setattr__(self, name, value)


def validate_project_paths(paths: ProjectPaths) -> None:
    """Require all declared project inputs to be regular files."""

    for name in (
        "netlist",
        "specifications",
        "design_intent",
        "design_rules",
        "simulation",
    ):
        path = getattr(paths, name)
        if not path.exists():
            raise InputError(f"required project input does not exist: {name}={path}")
        if not path.is_file():
            raise InputError(f"required project input is not a file: {name}={path}")

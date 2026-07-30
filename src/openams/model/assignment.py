"""Canonical assignment values and synthesis status."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ._immutable import immutable_mapping, require_nonempty

ScalarValue = bool | int | float | str | None


class AssignmentStatus(StrEnum):
    PARTIAL = "partial"
    RESOLVED = "resolved"
    SIMULATION_READY = "simulation_ready"
    SIMULATED = "simulated"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


@dataclass(frozen=True, slots=True)
class Assignment:
    name: str
    values: Mapping[str, ScalarValue]
    status: AssignmentStatus = AssignmentStatus.PARTIAL
    diagnostics: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        if not isinstance(self.status, AssignmentStatus):
            raise TypeError("status must be an AssignmentStatus")
        values = {
            require_nonempty(name, "variable name"): value
            for name, value in self.values.items()
        }
        for name, value in values.items():
            if not isinstance(value, (bool, int, float, str, type(None))):
                raise TypeError(f"assignment value for {name!r} must be scalar")
        diagnostics = tuple(require_nonempty(item, "diagnostic") for item in self.diagnostics)
        object.__setattr__(self, "values", immutable_mapping(values))
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "provenance", immutable_mapping(self.provenance))

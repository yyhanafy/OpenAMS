"""Technology query contract and immutable results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ._immutable import immutable_mapping, require_nonempty
from .assignment import ScalarValue


@dataclass(frozen=True, slots=True)
class DeviceQuery:
    device_kind: str
    known: Mapping[str, ScalarValue]
    solve_for: tuple[str, ...]
    conditions: Mapping[str, ScalarValue] = field(default_factory=dict)
    polarity: str | None = None
    model: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_kind", require_nonempty(self.device_kind, "device_kind"))
        if self.polarity is not None:
            object.__setattr__(self, "polarity", require_nonempty(self.polarity, "polarity"))
        if self.model is not None:
            object.__setattr__(self, "model", require_nonempty(self.model, "model"))
        solve_for = tuple(require_nonempty(name, "solve_for name") for name in self.solve_for)
        if not solve_for:
            raise ValueError("solve_for must contain at least one quantity")
        if len(solve_for) != len(set(solve_for)):
            raise ValueError("solve_for entries must be unique")
        overlap = set(self.known) & set(solve_for)
        if overlap:
            raise ValueError("known and solve_for must not overlap: " + ", ".join(sorted(overlap)))
        object.__setattr__(self, "known", immutable_mapping(self.known))
        object.__setattr__(self, "solve_for", solve_for)
        object.__setattr__(self, "conditions", immutable_mapping(self.conditions))
        object.__setattr__(self, "context", immutable_mapping(self.context))


@dataclass(frozen=True, slots=True)
class DeviceSolution:
    values: Mapping[str, ScalarValue]
    valid: bool
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    residuals: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.valid, bool):
            raise TypeError("valid must be a bool")
        object.__setattr__(self, "values", immutable_mapping(self.values))
        object.__setattr__(self, "diagnostics", immutable_mapping(self.diagnostics))
        object.__setattr__(self, "residuals", immutable_mapping(self.residuals))


@runtime_checkable
class TechnologyModel(Protocol):
    """Canonical technology backend interface."""

    def solve(self, query: DeviceQuery) -> DeviceSolution:
        """Solve one physical device query."""
        ...

"""Canonical simulation and evaluation results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ._immutable import immutable_mapping, require_nonempty
from .assignment import ScalarValue


@dataclass(frozen=True, slots=True)
class SimulationResult:
    assignment_name: str
    simulator: str
    analyses: Mapping[str, Mapping[str, ScalarValue]]
    success: bool
    diagnostics: tuple[str, ...] = ()
    artifacts: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assignment_name", require_nonempty(self.assignment_name, "assignment_name")
        )
        object.__setattr__(self, "simulator", require_nonempty(self.simulator, "simulator"))
        if not isinstance(self.success, bool):
            raise TypeError("success must be a bool")
        analyses = {
            require_nonempty(name, "analysis name"): immutable_mapping(values)
            for name, values in self.analyses.items()
        }
        artifacts = {
            require_nonempty(name, "artifact name"): require_nonempty(path, "artifact path")
            for name, path in self.artifacts.items()
        }
        diagnostics = tuple(require_nonempty(item, "diagnostic") for item in self.diagnostics)
        object.__setattr__(self, "analyses", immutable_mapping(analyses))
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "artifacts", immutable_mapping(artifacts))


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    assignment_name: str
    passed: bool
    checks: Mapping[str, bool]
    score: float | None = None
    margins: Mapping[str, float] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assignment_name", require_nonempty(self.assignment_name, "assignment_name")
        )
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a bool")
        checks = {
            require_nonempty(name, "check name"): value
            for name, value in self.checks.items()
        }
        if not all(isinstance(value, bool) for value in checks.values()):
            raise TypeError("all evaluation checks must be bool values")
        if self.score is not None and isinstance(self.score, bool):
            raise TypeError("score must be a real number or None")
        if self.score is not None and not isinstance(self.score, (int, float)):
            raise TypeError("score must be a real number or None")
        margins = {
            require_nonempty(name, "margin name"): float(value)
            for name, value in self.margins.items()
        }
        diagnostics = tuple(require_nonempty(item, "diagnostic") for item in self.diagnostics)
        object.__setattr__(self, "checks", immutable_mapping(checks))
        object.__setattr__(self, "score", None if self.score is None else float(self.score))
        object.__setattr__(self, "margins", immutable_mapping(margins))
        object.__setattr__(self, "diagnostics", diagnostics)

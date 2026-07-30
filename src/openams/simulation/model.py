"""Immutable backend-neutral simulation manifest objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from openams.model import Assignment, AssignmentStatus

from .errors import InvalidSimulationManifestError


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


def _name(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise InvalidSimulationManifestError(f"{label} must be non-empty")
    return value


@dataclass(frozen=True, slots=True)
class SimulationBackend:
    """Logical simulator selection without backend implementation details."""

    name: str
    version: str | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name, "backend name"))
        if self.version is not None:
            object.__setattr__(self, "version", _name(self.version, "backend version"))
        object.__setattr__(self, "options", _freeze(self.options))


@dataclass(frozen=True, slots=True)
class SimulationTemplate:
    """External circuit template reference consumed by a backend adapter."""

    name: str
    source: str
    parameter_bindings: Mapping[str, str]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name, "template name"))
        object.__setattr__(self, "source", _name(self.source, "template source"))
        bindings: dict[str, str] = {}
        targets: set[str] = set()
        for variable, target in self.parameter_bindings.items():
            variable = _name(variable, "canonical variable")
            target = _name(target, "template parameter")
            if variable in bindings:
                raise InvalidSimulationManifestError(
                    f"duplicate canonical variable {variable!r}"
                )
            if target in targets:
                raise InvalidSimulationManifestError(
                    f"template parameter {target!r} is bound more than once"
                )
            bindings[variable] = target
            targets.add(target)
        if not bindings:
            raise InvalidSimulationManifestError(
                "parameter_bindings must not be empty"
            )
        object.__setattr__(self, "parameter_bindings", _freeze(bindings))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True, slots=True)
class SimulationCase:
    """One immutable assignment prepared for simulator rendering."""

    name: str
    assignment: Assignment
    rendered_parameters: Mapping[str, float]
    analyses: tuple[str, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name, "simulation case name"))
        if self.assignment.status is not AssignmentStatus.SIMULATION_READY:
            raise InvalidSimulationManifestError(
                "simulation case assignment must be simulation-ready"
            )
        rendered: dict[str, float] = {}
        for name, value in self.rendered_parameters.items():
            name = _name(name, "rendered parameter name")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidSimulationManifestError(
                    f"rendered parameter {name!r} must be numeric"
                )
            rendered[name] = float(value)
        if not rendered:
            raise InvalidSimulationManifestError(
                "rendered_parameters must not be empty"
            )
        analyses = tuple(_name(item, "analysis name") for item in self.analyses)
        if not analyses:
            raise InvalidSimulationManifestError("at least one analysis is required")
        if len(set(analyses)) != len(analyses):
            raise InvalidSimulationManifestError("analysis names must be unique")
        object.__setattr__(self, "rendered_parameters", _freeze(rendered))
        object.__setattr__(self, "analyses", analyses)
        object.__setattr__(self, "provenance", _freeze(self.provenance))


@dataclass(frozen=True, slots=True)
class SimulationManifest:
    """Complete backend-neutral batch submitted to one simulator adapter."""

    name: str
    backend: SimulationBackend
    template: SimulationTemplate
    cases: tuple[SimulationCase, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name, "manifest name"))
        cases = tuple(self.cases)
        names = tuple(case.name for case in cases)
        if len(set(names)) != len(names):
            raise InvalidSimulationManifestError(
                "simulation case names must be unique"
            )
        object.__setattr__(self, "cases", cases)
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    @property
    def case_count(self) -> int:
        return len(self.cases)


@dataclass(frozen=True, slots=True)
class SimulationRunRequest:
    """Filesystem-neutral request understood by concrete runner adapters."""

    manifest: SimulationManifest
    workspace: str
    max_workers: int = 1
    keep_intermediate_files: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", _name(self.workspace, "workspace"))
        if self.max_workers < 1:
            raise InvalidSimulationManifestError("max_workers must be positive")
        if not isinstance(self.keep_intermediate_files, bool):
            raise TypeError("keep_intermediate_files must be boolean")
        object.__setattr__(self, "metadata", _freeze(self.metadata))

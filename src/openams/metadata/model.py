"""Immutable semantic metadata objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class TechnologySourceConfig:
    """One semantic technology-provider declaration.

    `source` is an opaque external reference. Metadata does not interpret it as
    a filesystem path and does not check its existence.
    """

    name: str
    provider: str
    source: str
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = self.name.strip()
        provider = self.provider.strip()
        source = self.source.strip()
        if not name:
            raise ValueError("technology source name must not be empty")
        if not provider:
            raise ValueError(f"technology source {name!r} requires a provider")
        if not source:
            raise ValueError(f"technology source {name!r} requires a source")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "options", _freeze(self.options))


@dataclass(frozen=True, slots=True)
class TechnologyConfig:
    """Selected technology source plus all declared sources."""

    active_source: str
    sources: Mapping[str, TechnologySourceConfig]

    def __post_init__(self) -> None:
        active = self.active_source.strip()
        frozen = MappingProxyType(dict(self.sources))
        if not active:
            raise ValueError("active technology source must not be empty")
        if active not in frozen:
            raise ValueError(
                f"active technology source {active!r} is not declared"
            )
        object.__setattr__(self, "active_source", active)
        object.__setattr__(self, "sources", frozen)

    @property
    def active(self) -> TechnologySourceConfig:
        return self.sources[self.active_source]


@dataclass(frozen=True, slots=True)
class ProjectInputs:
    """Normalized semantic inputs independent of files and serialization."""

    specifications: Mapping[str, Any]
    design_intent: Mapping[str, Any]
    design_rules: Mapping[str, Any]
    simulation: Mapping[str, Any]
    technology: TechnologyConfig

    def __post_init__(self) -> None:
        object.__setattr__(self, "specifications", _freeze(self.specifications))
        object.__setattr__(self, "design_intent", _freeze(self.design_intent))
        object.__setattr__(self, "design_rules", _freeze(self.design_rules))
        object.__setattr__(self, "simulation", _freeze(self.simulation))

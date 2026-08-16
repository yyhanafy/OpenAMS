"""Immutable table-backend value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from openams.technology import (
    CharacterizationPoint,
    TechnologyCapabilities,
    TechnologyIdentity,
)

from ._keys import exact_characterization_key
from .errors import DuplicateCharacterizationPointError


class BracketAxis(str, Enum):
    LENGTH = "length_m"
    WIDTH = "width_m"
    VGS = "vgs_v"
    VDS = "vds_v"
    VBS = "vbs_v"
    TEMPERATURE = "temperature_c"


@dataclass(frozen=True, slots=True, kw_only=True)
class BracketResult:
    axis: BracketAxis
    target: float
    lower: CharacterizationPoint | None
    upper: CharacterizationPoint | None

    @property
    def is_exact(self) -> bool:
        return self.lower is not None and self.lower is self.upper

    @property
    def is_complete(self) -> bool:
        return self.lower is not None and self.upper is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class CharacterizationTable:
    identity: TechnologyIdentity
    capabilities: TechnologyCapabilities
    points: tuple[CharacterizationPoint, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, TechnologyIdentity):
            raise TypeError("identity must be a TechnologyIdentity")
        if not isinstance(self.capabilities, TechnologyCapabilities):
            raise TypeError("capabilities must be TechnologyCapabilities")

        points = tuple(self.points)
        if not points:
            raise ValueError("characterization table requires at least one point")
        if not all(isinstance(point, CharacterizationPoint) for point in points):
            raise TypeError(
                "points must contain CharacterizationPoint values"
            )

        seen: dict[tuple[object, ...], int] = {}
        for index, point in enumerate(points):
            key = exact_characterization_key(point)
            if key in seen:
                raise DuplicateCharacterizationPointError(
                    "duplicate exact characterization point at indices "
                    f"{seen[key]} and {index}"
                )
            seen[key] = index

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        object.__setattr__(self, "points", points)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

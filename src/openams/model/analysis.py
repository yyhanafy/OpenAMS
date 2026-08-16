"""Simulator-independent analysis requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ._immutable import immutable_mapping, require_nonempty


class AnalysisKind(StrEnum):
    DC_OPERATING_POINT = "dc_operating_point"
    AC = "ac"
    TRANSIENT = "transient"


@dataclass(frozen=True, slots=True)
class Analysis:
    name: str
    kind: AnalysisKind
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        if not isinstance(self.kind, AnalysisKind):
            raise TypeError("kind must be an AnalysisKind")
        object.__setattr__(self, "options", immutable_mapping(self.options))

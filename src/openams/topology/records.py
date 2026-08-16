"""Private immutable parser records."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ParsedDevice:
    name: str
    kind: str
    model: str | None
    terminals: Mapping[str, str]
    parameters: Mapping[str, Any]
    source_line: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "terminals", MappingProxyType(dict(self.terminals)))
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

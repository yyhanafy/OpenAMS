"""Canonical OpenAMS constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from collections.abc import Mapping

from ._immutable import immutable_mapping, require_nonempty


class ConstraintKind(StrEnum):
    EQUALITY = "equality"
    INEQUALITY = "inequality"
    RANGE = "range"
    MEMBERSHIP = "membership"
    LOGICAL = "logical"
    TECHNOLOGY_QUERY = "technology_query"
    TOPOLOGY_DERIVED = "topology_derived"


@dataclass(frozen=True, slots=True)
class Constraint:
    """One declarative relationship that must hold."""

    name: str
    kind: ConstraintKind
    expression: str
    source: str
    variables: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        object.__setattr__(self, "expression", require_nonempty(self.expression, "expression"))
        object.__setattr__(self, "source", require_nonempty(self.source, "source"))
        if not isinstance(self.kind, ConstraintKind):
            raise TypeError("kind must be a ConstraintKind")
        normalized_variables = tuple(require_nonempty(v, "variable name") for v in self.variables)
        if len(normalized_variables) != len(set(normalized_variables)):
            raise ValueError("constraint variables must be unique")
        object.__setattr__(self, "variables", normalized_variables)
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

"""Canonical OpenAMS variables and variable metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ._immutable import require_nonempty


class VariableRole(StrEnum):
    """How a variable is populated in a particular execution context."""

    CONSTANT = "constant"
    INDEPENDENT = "independent"
    DERIVED = "derived"
    TECHNOLOGY_SOLVED = "technology_solved"
    SIMULATOR_MEASURED = "simulator_measured"
    OBJECTIVE = "objective"


class Quantity(StrEnum):
    """Initial canonical physical and logical quantity categories."""

    DIMENSIONLESS = "dimensionless"
    VOLTAGE = "voltage"
    CURRENT = "current"
    LENGTH = "length"
    CAPACITANCE = "capacitance"
    RESISTANCE = "resistance"
    CONDUCTANCE = "conductance"
    FREQUENCY = "frequency"
    TIME = "time"
    POWER = "power"
    TEMPERATURE = "temperature"
    ANGLE = "angle"
    BOOLEAN = "boolean"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class Variable:
    """Identity and metadata for one canonical OpenAMS quantity."""

    name: str
    quantity: Quantity
    unit: str
    role: VariableRole
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        object.__setattr__(self, "unit", require_nonempty(self.unit, "unit"))
        if not isinstance(self.quantity, Quantity):
            raise TypeError("quantity must be a Quantity")
        if not isinstance(self.role, VariableRole):
            raise TypeError("role must be a VariableRole")
        if self.description is not None:
            object.__setattr__(
                self,
                "description",
                require_nonempty(self.description, "description"),
            )

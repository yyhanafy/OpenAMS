"""Canonical circuit topology objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ._immutable import immutable_mapping, require_nonempty
from .analysis import Analysis
from .constraint import Constraint
from .specification import Specification
from .variable import Variable


class NodeKind(StrEnum):
    ELECTRICAL = "electrical"


class DeviceKind(StrEnum):
    MOS = "mos"
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    VOLTAGE_SOURCE = "voltage_source"
    CURRENT_SOURCE = "current_source"


@dataclass(frozen=True, slots=True)
class Node:
    name: str
    kind: NodeKind = NodeKind.ELECTRICAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        if not isinstance(self.kind, NodeKind):
            raise TypeError("kind must be a NodeKind")


@dataclass(frozen=True, slots=True)
class Terminal:
    name: str
    node: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        object.__setattr__(self, "node", require_nonempty(self.node, "node"))


@dataclass(frozen=True, slots=True)
class Device:
    name: str
    kind: DeviceKind
    terminals: Mapping[str, str]
    model: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        if not isinstance(self.kind, DeviceKind):
            raise TypeError("kind must be a DeviceKind")
        if self.model is not None:
            object.__setattr__(self, "model", require_nonempty(self.model, "model"))
        terminals = {
            require_nonempty(name, "terminal name"): require_nonempty(node, "terminal node")
            for name, node in self.terminals.items()
        }
        if not terminals:
            raise ValueError("device must have at least one terminal")
        object.__setattr__(self, "terminals", immutable_mapping(terminals))
        object.__setattr__(self, "parameters", immutable_mapping(self.parameters))
        object.__setattr__(self, "provenance", immutable_mapping(self.provenance))


@dataclass(frozen=True, slots=True)
class Circuit:
    name: str
    nodes: Mapping[str, Node]
    devices: Mapping[str, Device]
    variables: Mapping[str, Variable] = field(default_factory=dict)
    constraints: tuple[Constraint, ...] = ()
    analyses: tuple[Analysis, ...] = ()
    specifications: tuple[Specification, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonempty(self.name, "name"))
        nodes = dict(self.nodes)
        devices = dict(self.devices)
        variables = dict(self.variables)

        self._validate_named_mapping(nodes, Node, "node")
        self._validate_named_mapping(devices, Device, "device")
        self._validate_named_mapping(variables, Variable, "variable")

        for device in devices.values():
            missing = sorted(set(device.terminals.values()) - set(nodes))
            if missing:
                raise ValueError(
                    f"device {device.name!r} references unknown nodes: {', '.join(missing)}"
                )

        constraint_names = [item.name for item in self.constraints]
        analysis_names = [item.name for item in self.analyses]
        specification_names = [item.name for item in self.specifications]
        self._require_unique(constraint_names, "constraint")
        self._require_unique(analysis_names, "analysis")
        self._require_unique(specification_names, "specification")

        unknown_variables = {
            variable_name
            for constraint in self.constraints
            for variable_name in constraint.variables
            if variable_name not in variables
        }
        if unknown_variables:
            raise ValueError(
                "constraints reference unknown variables: "
                + ", ".join(sorted(unknown_variables))
            )

        object.__setattr__(self, "nodes", immutable_mapping(nodes))
        object.__setattr__(self, "devices", immutable_mapping(devices))
        object.__setattr__(self, "variables", immutable_mapping(variables))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "analyses", tuple(self.analyses))
        object.__setattr__(self, "specifications", tuple(self.specifications))
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @staticmethod
    def _validate_named_mapping(values: Mapping[str, Any], expected_type: type, label: str) -> None:
        for key, value in values.items():
            normalized_key = require_nonempty(key, f"{label} key")
            if not isinstance(value, expected_type):
                raise TypeError(f"{label} {normalized_key!r} has the wrong type")
            if normalized_key != value.name:
                raise ValueError(
                    f"{label} mapping key {normalized_key!r} does not match object name {value.name!r}"
                )

    @staticmethod
    def _require_unique(names: list[str], label: str) -> None:
        if len(names) != len(set(names)):
            raise ValueError(f"{label} names must be unique")

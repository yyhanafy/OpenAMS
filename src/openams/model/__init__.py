"""Public immutable OpenAMS domain model."""

from .analysis import Analysis, AnalysisKind
from .assignment import Assignment, AssignmentStatus, ScalarValue
from .circuit import Circuit, Device, DeviceKind, Node, NodeKind, Terminal
from .constraint import Constraint, ConstraintKind
from .result import EvaluationResult, SimulationResult
from .specification import ComparisonRelation, Specification, SpecificationSeverity
from .technology import DeviceQuery, DeviceSolution, TechnologyModel
from .variable import Quantity, Variable, VariableRole

__all__ = [
    "Analysis",
    "AnalysisKind",
    "Assignment",
    "AssignmentStatus",
    "Circuit",
    "ComparisonRelation",
    "Constraint",
    "ConstraintKind",
    "Device",
    "DeviceKind",
    "DeviceQuery",
    "DeviceSolution",
    "EvaluationResult",
    "Node",
    "NodeKind",
    "Quantity",
    "ScalarValue",
    "SimulationResult",
    "Specification",
    "SpecificationSeverity",
    "TechnologyModel",
    "Terminal",
    "Variable",
    "VariableRole",
]

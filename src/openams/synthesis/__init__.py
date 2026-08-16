"""Explicit circuit-region synthesis by deterministic region intersection."""

from .assignments import (
    CircuitRegionAssignmentEmitter,
    FixedAssignmentBatch,
    FixedAssignmentPolicy,
    FixedAssignmentRecord,
)
from .compiler import (
    CircuitConstraintCompiler,
    CompiledIntersection,
    ConstraintCompilationDiagnostic,
    RegionBinding,
)
from .constraints import (
    AllowedValuesConstraint,
    CircuitConstraint,
    FieldRelationConstraint,
    SumConstraint,
)
from .errors import (
    CombinationBudgetExceededError,
    InvalidRegionError,
    MissingFieldError,
    SynthesisError,
)
from .indexed import PlannedIntersectionPolicy, PlannedRegionIntersection
from .intersection import IntersectionPolicy, RegionIntersection
from .planning import IntersectionPlanner, JoinKey, JoinPlan, JoinStep
from .model import (
    CircuitRegion,
    CircuitRow,
    ConstraintDecision,
    RegionInput,
    RejectedCombination,
)

__all__ = [
    "AllowedValuesConstraint",
    "FixedAssignmentRecord",
    "FixedAssignmentPolicy",
    "FixedAssignmentBatch",
    "CircuitRegionAssignmentEmitter",
    "RegionBinding",
    "ConstraintCompilationDiagnostic",
    "CompiledIntersection",
    "CircuitConstraintCompiler",
    "CircuitConstraint",
    "CircuitRegion",
    "CircuitRow",
    "CombinationBudgetExceededError",
    "ConstraintDecision",
    "FieldRelationConstraint",
    "IntersectionPlanner",
    "IntersectionPolicy",
    "JoinKey",
    "JoinPlan",
    "JoinStep",
    "InvalidRegionError",
    "MissingFieldError",
    "PlannedIntersectionPolicy",
    "PlannedRegionIntersection",
    "RegionInput",
    "RegionIntersection",
    "RejectedCombination",
    "SumConstraint",
    "SynthesisError",
    "SynthesisWorkflowResult",
    "SynthesisStage",
    "StageResult",
    "HierarchicalSynthesisWorkflow",
    "CanonicalConstraintRecord",
]

from .workflow import (
    CanonicalConstraintRecord,
    HierarchicalSynthesisWorkflow,
    StageResult,
    SynthesisStage,
    SynthesisWorkflowResult,
)

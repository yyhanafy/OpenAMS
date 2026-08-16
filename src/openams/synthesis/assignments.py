"""Convert explicit circuit-region rows into fixed execution assignments."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from openams.model import Assignment, AssignmentStatus
from openams.planning import (
    ExecutionPlan,
    ExecutionRoute,
    PlanningRequest,
    build_execution_plan,
)

from .errors import InvalidRegionError, MissingFieldError, SynthesisError
from .model import CircuitRegion, CircuitRow


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


def _require_name(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise SynthesisError(f"{label} must be non-empty")
    return value


@dataclass(frozen=True)
class FixedAssignmentPolicy:
    """Controls deterministic assignment materialization from circuit rows."""

    name_prefix: str = "assignment"
    start_index: int = 0
    index_width: int = 6
    require_finite_numeric_values: bool = True
    reject_unmapped_row_fields: bool = False
    require_simulation: bool = True
    require_specification_verification: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "name_prefix", _require_name(self.name_prefix, "name_prefix"))
        if self.start_index < 0:
            raise ValueError("start_index must be non-negative")
        if self.index_width < 1:
            raise ValueError("index_width must be positive")
        for name in (
            "require_finite_numeric_values",
            "reject_unmapped_row_fields",
            "require_simulation",
            "require_specification_verification",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be boolean")
        if self.require_specification_verification and not self.require_simulation:
            raise ValueError("specification verification requires simulation")


@dataclass(frozen=True)
class FixedAssignmentRecord:
    """One resolved assignment and its immutable execution plan."""

    assignment: Assignment
    plan: ExecutionPlan
    source_row_index: int
    source_indices: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.assignment.status is not AssignmentStatus.SIMULATION_READY:
            raise ValueError("fixed assignment must be simulation-ready")
        if self.plan.route is not ExecutionRoute.DIRECT_SIMULATION:
            raise ValueError("fixed assignment must use direct-simulation route")
        if self.source_row_index < 0:
            raise ValueError("source_row_index must be non-negative")
        object.__setattr__(self, "source_indices", _freeze(self.source_indices))


@dataclass(frozen=True)
class FixedAssignmentBatch:
    """All fixed assignments emitted from one explicit circuit region."""

    records: tuple[FixedAssignmentRecord, ...]
    canonical_to_synthesis: Mapping[str, str]
    source_region_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(
            self, "canonical_to_synthesis", _freeze(self.canonical_to_synthesis)
        )
        object.__setattr__(
            self, "source_region_metadata", _freeze(self.source_region_metadata)
        )
        names = tuple(record.assignment.name for record in self.records)
        if len(set(names)) != len(names):
            raise ValueError("fixed assignment names must be unique")

    @property
    def assignments(self) -> tuple[Assignment, ...]:
        return tuple(record.assignment for record in self.records)

    @property
    def plans(self) -> tuple[ExecutionPlan, ...]:
        return tuple(record.plan for record in self.records)

    @property
    def count(self) -> int:
        return len(self.records)


class CircuitRegionAssignmentEmitter:
    """Materialize canonical, simulation-ready assignments from circuit rows.

    ``canonical_to_synthesis`` maps canonical variable names, such as
    ``device.M1.width``, to fields present in each ``CircuitRow``, such as
    ``input_pair.M1.w``.  The complete mapping is applied atomically to every
    row so correlations created during synthesis cannot be broken.
    """

    def __init__(self, policy: FixedAssignmentPolicy | None = None) -> None:
        self._policy = policy or FixedAssignmentPolicy()

    def emit(
        self,
        region: CircuitRegion,
        canonical_to_synthesis: Mapping[str, str],
        *,
        required_variables: Sequence[str] | None = None,
    ) -> FixedAssignmentBatch:
        mapping = self._normalize_mapping(canonical_to_synthesis)
        required = self._normalize_required(required_variables, mapping)
        records = tuple(
            self._emit_row(region, row, row_index, mapping, required)
            for row_index, row in enumerate(region.rows)
        )
        return FixedAssignmentBatch(
            records=records,
            canonical_to_synthesis=mapping,
            source_region_metadata={
                **dict(region.metadata),
                "source_kind": "circuit_region",
                "source_retained_count": region.retained_count,
                "assignment_count": len(records),
            },
        )

    def _normalize_mapping(self, mapping: Mapping[str, str]) -> Mapping[str, str]:
        if not mapping:
            raise SynthesisError("canonical_to_synthesis mapping must not be empty")
        normalized: dict[str, str] = {}
        synthesis_fields: set[str] = set()
        for canonical, synthesis in mapping.items():
            canonical = _require_name(canonical, "canonical variable name")
            synthesis = _require_name(synthesis, "synthesis field name")
            if canonical in normalized:
                raise SynthesisError(f"duplicate canonical variable {canonical!r}")
            if synthesis in synthesis_fields:
                raise SynthesisError(
                    f"synthesis field {synthesis!r} is mapped to more than one canonical variable"
                )
            normalized[canonical] = synthesis
            synthesis_fields.add(synthesis)
        return _freeze(normalized)

    @staticmethod
    def _normalize_required(
        required_variables: Sequence[str] | None,
        mapping: Mapping[str, str],
    ) -> frozenset[str]:
        if required_variables is None:
            return frozenset(mapping)
        required = frozenset(
            _require_name(name, "required variable") for name in required_variables
        )
        missing = required.difference(mapping)
        if missing:
            raise MissingFieldError(
                "required canonical variables are not mapped: " + ", ".join(sorted(missing))
            )
        return required

    def _emit_row(
        self,
        region: CircuitRegion,
        row: CircuitRow,
        row_index: int,
        mapping: Mapping[str, str],
        required: frozenset[str],
    ) -> FixedAssignmentRecord:
        values: dict[str, float] = {}
        for canonical, synthesis in mapping.items():
            if synthesis not in row.values:
                raise MissingFieldError(
                    f"circuit row {row_index} is missing mapped field {synthesis!r} "
                    f"for {canonical!r}"
                )
            values[canonical] = self._numeric_value(
                row.values[synthesis], canonical=canonical, row_index=row_index
            )

        missing_required = required.difference(values)
        if missing_required:
            raise MissingFieldError(
                f"circuit row {row_index} is missing required variables: "
                + ", ".join(sorted(missing_required))
            )

        if self._policy.reject_unmapped_row_fields:
            unmapped = set(row.values).difference(mapping.values())
            if unmapped:
                raise InvalidRegionError(
                    f"circuit row {row_index} contains unmapped fields: "
                    + ", ".join(sorted(unmapped))
                )

        name = (
            f"{self._policy.name_prefix}_"
            f"{self._policy.start_index + row_index:0{self._policy.index_width}d}"
        )
        provenance = {
            "source_kind": "circuit_region_row",
            "source_row_index": row_index,
            "source_indices": dict(row.source_indices),
            "region_metadata": dict(region.metadata),
            "canonical_to_synthesis": dict(mapping),
        }
        assignment = Assignment(
            name=name,
            values=values,
            status=AssignmentStatus.SIMULATION_READY,
            provenance=provenance,
        )
        plan = build_execution_plan(
            PlanningRequest(
                name=name,
                variables=frozenset(values),
                resolved_values=values,
                require_simulation=self._policy.require_simulation,
                require_specification_verification=(
                    self._policy.require_specification_verification
                ),
                provenance={
                    "source_assignment": name,
                    "source_kind": "fixed_synthesis_assignment",
                    "source_row_index": row_index,
                },
            )
        )
        return FixedAssignmentRecord(
            assignment=assignment,
            plan=plan,
            source_row_index=row_index,
            source_indices=row.source_indices,
        )

    def _numeric_value(self, value: Any, *, canonical: str, row_index: int) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidRegionError(
                f"circuit row {row_index} value for {canonical!r} must be numeric"
            )
        number = float(value)
        if self._policy.require_finite_numeric_values and not isfinite(number):
            raise InvalidRegionError(
                f"circuit row {row_index} value for {canonical!r} must be finite"
            )
        return number

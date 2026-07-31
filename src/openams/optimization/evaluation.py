"""Backend-neutral candidate evaluation and ranking.

This layer converts specification-screened simulation cases into explicit
candidate states and optional objective values suitable for ranking and
optimizer feedback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Iterable, Mapping, Sequence

from openams.simulation.screening import (
    CaseScreeningResult,
    ScreeningOutcome,
)


class EvaluationError(RuntimeError):
    """Base error for candidate evaluation."""


class CandidateState(str, Enum):
    VALID = "valid"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


class ObjectiveDirection(str, Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass(frozen=True)
class ObjectiveDefinition:
    """One scalar ranking objective derived from a screened measurement."""

    name: str
    measurement: str
    analysis: str
    direction: ObjectiveDirection
    weight: float = 1.0
    required: bool = True
    normalization_scale: float | None = None
    reference_value: float = 0.0
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("objective name must be non-empty")
        if not self.measurement.strip():
            raise ValueError("measurement name must be non-empty")
        if not self.analysis.strip():
            raise ValueError("analysis name must be non-empty")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError("objective weight must be finite and non-negative")
        if self.normalization_scale is not None:
            if (
                not math.isfinite(self.normalization_scale)
                or self.normalization_scale <= 0
            ):
                raise ValueError(
                    "normalization_scale must be finite and positive"
                )
        if not math.isfinite(self.reference_value):
            raise ValueError("reference_value must be finite")


@dataclass(frozen=True)
class ObjectiveComponent:
    """Evaluated objective component for one candidate."""

    name: str
    measurement: str
    analysis: str
    direction: ObjectiveDirection
    status: str
    raw_value: float | None
    normalized_value: float | None
    weighted_value: float | None
    weight: float
    unit: str | None
    diagnostic: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.status == "available"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "measurement": self.measurement,
            "analysis": self.analysis,
            "direction": self.direction.value,
            "status": self.status,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "weighted_value": self.weighted_value,
            "weight": self.weight,
            "unit": self.unit,
            "diagnostic": self.diagnostic,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class OptimizerFeedback:
    """Compact optimizer-facing representation of one candidate."""

    candidate_id: str
    feasible: bool | None
    objective_value: float | None
    state: CandidateState
    failure_reasons: tuple[str, ...] = ()
    unknown_reasons: tuple[str, ...] = ()
    components: tuple[ObjectiveComponent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "feasible": self.feasible,
            "objective_value": self.objective_value,
            "state": self.state.value,
            "failure_reasons": list(self.failure_reasons),
            "unknown_reasons": list(self.unknown_reasons),
            "components": [component.to_dict() for component in self.components],
        }


@dataclass(frozen=True)
class CandidateEvaluation:
    """Complete evaluation preserving the source screening record."""

    candidate_id: str
    state: CandidateState
    aggregate_score: float | None
    objectives: tuple[ObjectiveComponent, ...]
    screening_result: CaseScreeningResult
    failure_reasons: tuple[str, ...] = ()
    unknown_reasons: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def rankable(self) -> bool:
        return (
            self.state is CandidateState.VALID
            and self.aggregate_score is not None
            and math.isfinite(self.aggregate_score)
        )

    def optimizer_feedback(self) -> OptimizerFeedback:
        feasible: bool | None
        if self.state is CandidateState.VALID:
            feasible = True
        elif self.state is CandidateState.INFEASIBLE:
            feasible = False
        else:
            feasible = None

        return OptimizerFeedback(
            candidate_id=self.candidate_id,
            feasible=feasible,
            objective_value=self.aggregate_score,
            state=self.state,
            failure_reasons=self.failure_reasons,
            unknown_reasons=self.unknown_reasons,
            components=self.objectives,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "state": self.state.value,
            "aggregate_score": self.aggregate_score,
            "rankable": self.rankable,
            "objectives": [objective.to_dict() for objective in self.objectives],
            "failure_reasons": list(self.failure_reasons),
            "unknown_reasons": list(self.unknown_reasons),
            "provenance": dict(self.provenance),
            "screening_result": self.screening_result.to_dict(),
        }


@dataclass(frozen=True)
class RankedCandidate:
    rank: int
    evaluation: CandidateEvaluation

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "evaluation": self.evaluation.to_dict(),
        }


@dataclass(frozen=True)
class CandidateEvaluationSummary:
    evaluations: tuple[CandidateEvaluation, ...]
    ranking: tuple[RankedCandidate, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def valid_count(self) -> int:
        return sum(
            item.state is CandidateState.VALID
            for item in self.evaluations
        )

    @property
    def infeasible_count(self) -> int:
        return sum(
            item.state is CandidateState.INFEASIBLE
            for item in self.evaluations
        )

    @property
    def unknown_count(self) -> int:
        return sum(
            item.state is CandidateState.UNKNOWN
            for item in self.evaluations
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": len(self.evaluations),
            "valid_count": self.valid_count,
            "infeasible_count": self.infeasible_count,
            "unknown_count": self.unknown_count,
            "evaluations": [item.to_dict() for item in self.evaluations],
            "ranking": [item.to_dict() for item in self.ranking],
            "provenance": dict(self.provenance),
        }


def _find_measurement(
    screening: CaseScreeningResult,
    objective: ObjectiveDefinition,
):
    matches = []
    for analysis in screening.raw_result.analyses:
        if analysis.analysis != objective.analysis:
            continue
        for measurement in analysis.measurements:
            if measurement.name == objective.measurement:
                matches.append(measurement)

    if not matches:
        return None, (
            f"objective measurement {objective.analysis}."
            f"{objective.measurement} is absent"
        )
    if len(matches) > 1:
        return matches[-1], (
            f"multiple objective measurements found; used final record "
            f"({len(matches)} total)"
        )
    return matches[0], None


def _evaluate_objective(
    screening: CaseScreeningResult,
    objective: ObjectiveDefinition,
) -> ObjectiveComponent:
    measurement, lookup_diagnostic = _find_measurement(screening, objective)

    if measurement is None:
        return ObjectiveComponent(
            name=objective.name,
            measurement=objective.measurement,
            analysis=objective.analysis,
            direction=objective.direction,
            status="missing",
            raw_value=None,
            normalized_value=None,
            weighted_value=None,
            weight=objective.weight,
            unit=objective.unit,
            diagnostic=lookup_diagnostic,
            provenance={"required": objective.required},
        )

    if not measurement.available or measurement.value is None:
        return ObjectiveComponent(
            name=objective.name,
            measurement=objective.measurement,
            analysis=objective.analysis,
            direction=objective.direction,
            status="unavailable",
            raw_value=measurement.value,
            normalized_value=None,
            weighted_value=None,
            weight=objective.weight,
            unit=objective.unit or measurement.unit,
            diagnostic=measurement.diagnostic or lookup_diagnostic,
            provenance={
                "required": objective.required,
                "measurement_status": measurement.status.value,
                "measurement_provenance": dict(measurement.provenance),
            },
        )

    value = measurement.value
    signed = (
        value - objective.reference_value
        if objective.direction is ObjectiveDirection.MAXIMIZE
        else objective.reference_value - value
    )
    normalized = (
        signed / objective.normalization_scale
        if objective.normalization_scale is not None
        else signed
    )
    weighted = normalized * objective.weight

    return ObjectiveComponent(
        name=objective.name,
        measurement=objective.measurement,
        analysis=objective.analysis,
        direction=objective.direction,
        status="available",
        raw_value=value,
        normalized_value=normalized,
        weighted_value=weighted,
        weight=objective.weight,
        unit=objective.unit or measurement.unit,
        diagnostic=lookup_diagnostic,
        provenance={
            "required": objective.required,
            "reference_value": objective.reference_value,
            "normalization_scale": objective.normalization_scale,
            "measurement_provenance": dict(measurement.provenance),
        },
    )


class CandidateEvaluationEngine:
    """Create optimizer-neutral candidate evaluations and rankings."""

    def __init__(
        self,
        objectives: Iterable[ObjectiveDefinition],
    ) -> None:
        self.objectives = tuple(objectives)
        if not self.objectives:
            raise ValueError("at least one objective definition is required")

        names = [item.name for item in self.objectives]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(
                "duplicate objective names: " + ", ".join(duplicates)
            )

    def evaluate_case(
        self,
        screening: CaseScreeningResult,
    ) -> CandidateEvaluation:
        failure_reasons = tuple(
            rule.rule_name
            for rule in screening.rules
            if rule.outcome is ScreeningOutcome.FAIL
        )
        unknown_reasons = tuple(
            rule.rule_name
            for rule in screening.rules
            if rule.outcome is ScreeningOutcome.UNKNOWN
        )

        objectives = tuple(
            _evaluate_objective(screening, definition)
            for definition in self.objectives
        )

        if screening.outcome is ScreeningOutcome.FAIL:
            state = CandidateState.INFEASIBLE
            score = None
        elif screening.outcome is ScreeningOutcome.UNKNOWN:
            state = CandidateState.UNKNOWN
            score = None
        else:
            missing_required = tuple(
                component.name
                for component, definition in zip(
                    objectives, self.objectives, strict=True
                )
                if definition.required and not component.available
            )
            if missing_required:
                state = CandidateState.UNKNOWN
                unknown_reasons = (
                    *unknown_reasons,
                    *(f"objective:{name}" for name in missing_required),
                )
                score = None
            else:
                state = CandidateState.VALID
                score = sum(
                    component.weighted_value
                    for component in objectives
                    if component.weighted_value is not None
                )

        return CandidateEvaluation(
            candidate_id=screening.case_name,
            state=state,
            aggregate_score=score,
            objectives=objectives,
            screening_result=screening,
            failure_reasons=failure_reasons,
            unknown_reasons=unknown_reasons,
            provenance={
                "objective_count": len(self.objectives),
                "screening_outcome": screening.outcome.value,
            },
        )

    def evaluate_many(
        self,
        screenings: Iterable[CaseScreeningResult],
    ) -> CandidateEvaluationSummary:
        evaluations = tuple(
            self.evaluate_case(screening)
            for screening in screenings
        )
        rankable = sorted(
            (item for item in evaluations if item.rankable),
            key=lambda item: (
                -float(item.aggregate_score),
                item.candidate_id,
            ),
        )
        ranking = tuple(
            RankedCandidate(rank=index, evaluation=item)
            for index, item in enumerate(rankable, start=1)
        )
        return CandidateEvaluationSummary(
            evaluations=evaluations,
            ranking=ranking,
            provenance={"objective_count": len(self.objectives)},
        )

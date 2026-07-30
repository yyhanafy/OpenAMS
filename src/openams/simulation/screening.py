"""Specification screening for backend-neutral raw simulation results.

This layer evaluates explicit specification rules against parsed scalar
measurements.  It never mutates, replaces, or reinterprets the raw simulation
records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Iterable, Mapping, Sequence

from .results import (
    MeasurementStatus,
    RawAnalysisResult,
    RawSimulationCaseResult,
    ScalarMeasurement,
)


class ScreeningError(RuntimeError):
    """Base error for specification screening."""


class ScreeningOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class ComparisonOperator(str, Enum):
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    EQUAL = "=="
    BETWEEN_INCLUSIVE = "between_inclusive"
    OUTSIDE_INCLUSIVE = "outside_inclusive"


@dataclass(frozen=True)
class SpecificationRule:
    """One explicit screening rule applied to a scalar measurement."""

    name: str
    measurement: str
    analysis: str
    operator: ComparisonOperator
    threshold: float | None = None
    lower: float | None = None
    upper: float | None = None
    tolerance: float = 0.0
    required: bool = True
    unit: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("rule name must be non-empty")
        if not self.measurement.strip():
            raise ValueError("measurement name must be non-empty")
        if not self.analysis.strip():
            raise ValueError("analysis name must be non-empty")
        if self.tolerance < 0 or not math.isfinite(self.tolerance):
            raise ValueError("tolerance must be finite and non-negative")

        scalar_operators = {
            ComparisonOperator.GREATER_THAN,
            ComparisonOperator.GREATER_THAN_OR_EQUAL,
            ComparisonOperator.LESS_THAN,
            ComparisonOperator.LESS_THAN_OR_EQUAL,
            ComparisonOperator.EQUAL,
        }
        range_operators = {
            ComparisonOperator.BETWEEN_INCLUSIVE,
            ComparisonOperator.OUTSIDE_INCLUSIVE,
        }

        if self.operator in scalar_operators:
            if self.threshold is None or not math.isfinite(self.threshold):
                raise ValueError(
                    f"operator {self.operator.value!r} requires a finite threshold"
                )
            if self.lower is not None or self.upper is not None:
                raise ValueError(
                    "scalar comparison rules must not define lower or upper bounds"
                )

        if self.operator in range_operators:
            if self.lower is None or self.upper is None:
                raise ValueError(
                    f"operator {self.operator.value!r} requires lower and upper bounds"
                )
            if not math.isfinite(self.lower) or not math.isfinite(self.upper):
                raise ValueError("range bounds must be finite")
            if self.lower > self.upper:
                raise ValueError("lower bound must not exceed upper bound")
            if self.threshold is not None:
                raise ValueError("range rules must not define threshold")


@dataclass(frozen=True)
class RuleScreeningResult:
    """Outcome of applying one specification rule."""

    rule_name: str
    measurement: str
    analysis: str
    outcome: ScreeningOutcome
    actual_value: float | None
    expected: Mapping[str, Any]
    unit: str | None
    diagnostic: str | None = None
    measurement_status: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.outcome is ScreeningOutcome.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "measurement": self.measurement,
            "analysis": self.analysis,
            "outcome": self.outcome.value,
            "actual_value": self.actual_value,
            "expected": dict(self.expected),
            "unit": self.unit,
            "diagnostic": self.diagnostic,
            "measurement_status": self.measurement_status,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class CaseScreeningResult:
    """Immutable screening report for one raw simulation case."""

    case_name: str
    outcome: ScreeningOutcome
    rules: tuple[RuleScreeningResult, ...]
    raw_result: RawSimulationCaseResult
    diagnostics: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.outcome is ScreeningOutcome.PASS

    @property
    def failed_rule_count(self) -> int:
        return sum(rule.outcome is ScreeningOutcome.FAIL for rule in self.rules)

    @property
    def unknown_rule_count(self) -> int:
        return sum(rule.outcome is ScreeningOutcome.UNKNOWN for rule in self.rules)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_name": self.case_name,
            "outcome": self.outcome.value,
            "passed": self.passed,
            "failed_rule_count": self.failed_rule_count,
            "unknown_rule_count": self.unknown_rule_count,
            "rules": [rule.to_dict() for rule in self.rules],
            "diagnostics": list(self.diagnostics),
            "provenance": dict(self.provenance),
            "raw_result": self.raw_result.to_dict(),
        }


@dataclass(frozen=True)
class ScreeningSummary:
    """Aggregate screening result for a batch of cases."""

    cases: tuple[CaseScreeningResult, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed_case_count(self) -> int:
        return sum(case.outcome is ScreeningOutcome.PASS for case in self.cases)

    @property
    def failed_case_count(self) -> int:
        return sum(case.outcome is ScreeningOutcome.FAIL for case in self.cases)

    @property
    def unknown_case_count(self) -> int:
        return sum(case.outcome is ScreeningOutcome.UNKNOWN for case in self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": len(self.cases),
            "passed_case_count": self.passed_case_count,
            "failed_case_count": self.failed_case_count,
            "unknown_case_count": self.unknown_case_count,
            "cases": [case.to_dict() for case in self.cases],
            "provenance": dict(self.provenance),
        }


def _expected_payload(rule: SpecificationRule) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operator": rule.operator.value,
        "tolerance": rule.tolerance,
    }
    if rule.threshold is not None:
        payload["threshold"] = rule.threshold
    if rule.lower is not None:
        payload["lower"] = rule.lower
    if rule.upper is not None:
        payload["upper"] = rule.upper
    return payload


def _compare(value: float, rule: SpecificationRule) -> bool:
    tolerance = rule.tolerance

    if rule.operator is ComparisonOperator.GREATER_THAN:
        assert rule.threshold is not None
        return value > rule.threshold - tolerance

    if rule.operator is ComparisonOperator.GREATER_THAN_OR_EQUAL:
        assert rule.threshold is not None
        return value >= rule.threshold - tolerance

    if rule.operator is ComparisonOperator.LESS_THAN:
        assert rule.threshold is not None
        return value < rule.threshold + tolerance

    if rule.operator is ComparisonOperator.LESS_THAN_OR_EQUAL:
        assert rule.threshold is not None
        return value <= rule.threshold + tolerance

    if rule.operator is ComparisonOperator.EQUAL:
        assert rule.threshold is not None
        return abs(value - rule.threshold) <= tolerance

    if rule.operator is ComparisonOperator.BETWEEN_INCLUSIVE:
        assert rule.lower is not None and rule.upper is not None
        return (
            value >= rule.lower - tolerance
            and value <= rule.upper + tolerance
        )

    if rule.operator is ComparisonOperator.OUTSIDE_INCLUSIVE:
        assert rule.lower is not None and rule.upper is not None
        return (
            value <= rule.lower + tolerance
            or value >= rule.upper - tolerance
        )

    raise ScreeningError(f"unsupported comparison operator: {rule.operator}")


def _find_measurement(
    raw_result: RawSimulationCaseResult,
    rule: SpecificationRule,
) -> tuple[ScalarMeasurement | None, str | None]:
    matching_analyses = [
        analysis
        for analysis in raw_result.analyses
        if analysis.analysis == rule.analysis
    ]
    if not matching_analyses:
        return None, f"analysis {rule.analysis!r} is absent"

    matches = [
        measurement
        for analysis in matching_analyses
        for measurement in analysis.measurements
        if measurement.name == rule.measurement
    ]
    if not matches:
        return (
            None,
            f"measurement {rule.measurement!r} is absent from analysis "
            f"{rule.analysis!r}",
        )

    if len(matches) > 1:
        return (
            matches[-1],
            f"multiple matching measurements found; used final record "
            f"({len(matches)} total)",
        )

    return matches[0], None


class SpecificationScreeningEngine:
    """Evaluate explicit specification rules against raw simulation results."""

    def __init__(self, rules: Iterable[SpecificationRule]) -> None:
        self.rules = tuple(rules)
        if not self.rules:
            raise ValueError("at least one specification rule is required")

        names = [rule.name for rule in self.rules]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(
                "duplicate specification rule names: " + ", ".join(duplicates)
            )

    def screen_case(
        self,
        raw_result: RawSimulationCaseResult,
    ) -> CaseScreeningResult:
        rule_results: list[RuleScreeningResult] = []
        diagnostics: list[str] = []

        for rule in self.rules:
            measurement, lookup_diagnostic = _find_measurement(raw_result, rule)
            expected = _expected_payload(rule)

            if measurement is None:
                outcome = (
                    ScreeningOutcome.UNKNOWN
                    if rule.required
                    else ScreeningOutcome.PASS
                )
                rule_results.append(
                    RuleScreeningResult(
                        rule_name=rule.name,
                        measurement=rule.measurement,
                        analysis=rule.analysis,
                        outcome=outcome,
                        actual_value=None,
                        expected=expected,
                        unit=rule.unit,
                        diagnostic=lookup_diagnostic,
                        measurement_status=None,
                        provenance={"required": rule.required},
                    )
                )
                continue

            if measurement.status is not MeasurementStatus.PRESENT:
                outcome = (
                    ScreeningOutcome.UNKNOWN
                    if rule.required
                    else ScreeningOutcome.PASS
                )
                diagnostic_parts = [
                    f"measurement status is {measurement.status.value}"
                ]
                if measurement.diagnostic:
                    diagnostic_parts.append(measurement.diagnostic)
                if lookup_diagnostic:
                    diagnostic_parts.append(lookup_diagnostic)

                rule_results.append(
                    RuleScreeningResult(
                        rule_name=rule.name,
                        measurement=rule.measurement,
                        analysis=rule.analysis,
                        outcome=outcome,
                        actual_value=None,
                        expected=expected,
                        unit=rule.unit or measurement.unit,
                        diagnostic="; ".join(diagnostic_parts),
                        measurement_status=measurement.status.value,
                        provenance={
                            "required": rule.required,
                            "measurement_provenance": dict(
                                measurement.provenance
                            ),
                        },
                    )
                )
                continue

            if measurement.value is None or not math.isfinite(measurement.value):
                outcome = (
                    ScreeningOutcome.UNKNOWN
                    if rule.required
                    else ScreeningOutcome.PASS
                )
                rule_results.append(
                    RuleScreeningResult(
                        rule_name=rule.name,
                        measurement=rule.measurement,
                        analysis=rule.analysis,
                        outcome=outcome,
                        actual_value=measurement.value,
                        expected=expected,
                        unit=rule.unit or measurement.unit,
                        diagnostic="measurement value is unavailable or non-finite",
                        measurement_status=measurement.status.value,
                        provenance={"required": rule.required},
                    )
                )
                continue

            passed = _compare(measurement.value, rule)
            diagnostic = lookup_diagnostic
            if not passed and rule.description:
                diagnostic = rule.description

            rule_results.append(
                RuleScreeningResult(
                    rule_name=rule.name,
                    measurement=rule.measurement,
                    analysis=rule.analysis,
                    outcome=(
                        ScreeningOutcome.PASS
                        if passed
                        else ScreeningOutcome.FAIL
                    ),
                    actual_value=measurement.value,
                    expected=expected,
                    unit=rule.unit or measurement.unit,
                    diagnostic=diagnostic,
                    measurement_status=measurement.status.value,
                    provenance={
                        "required": rule.required,
                        "measurement_provenance": dict(
                            measurement.provenance
                        ),
                    },
                )
            )

        case_outcome = self._aggregate_case_outcome(
            raw_result=raw_result,
            rule_results=rule_results,
        )

        if not raw_result.execution_succeeded:
            diagnostics.append("raw simulation execution did not succeed")

        return CaseScreeningResult(
            case_name=raw_result.case_name,
            outcome=case_outcome,
            rules=tuple(rule_results),
            raw_result=raw_result,
            diagnostics=tuple(diagnostics),
            provenance={
                "rule_count": len(self.rules),
                "raw_case_name": raw_result.case_name,
            },
        )

    def screen_many(
        self,
        raw_results: Iterable[RawSimulationCaseResult],
    ) -> ScreeningSummary:
        cases = tuple(self.screen_case(item) for item in raw_results)
        return ScreeningSummary(
            cases=cases,
            provenance={"rule_count": len(self.rules)},
        )

    @staticmethod
    def _aggregate_case_outcome(
        *,
        raw_result: RawSimulationCaseResult,
        rule_results: Sequence[RuleScreeningResult],
    ) -> ScreeningOutcome:
        if any(
            rule.outcome is ScreeningOutcome.FAIL
            for rule in rule_results
        ):
            return ScreeningOutcome.FAIL

        if (
            not raw_result.execution_succeeded
            or any(
                rule.outcome is ScreeningOutcome.UNKNOWN
                for rule in rule_results
            )
        ):
            return ScreeningOutcome.UNKNOWN

        return ScreeningOutcome.PASS

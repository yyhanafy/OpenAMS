from __future__ import annotations

from openams.simulation.results import (
    AnalysisStatus,
    MeasurementStatus,
    RawAnalysisResult,
    RawSimulationCaseResult,
    ScalarMeasurement,
)
from openams.simulation.screening import (
    ComparisonOperator,
    ScreeningOutcome,
    SpecificationRule,
    SpecificationScreeningEngine,
)


def measurement(
    name: str,
    value: float | None,
    *,
    analysis: str = "ac",
    status: MeasurementStatus = MeasurementStatus.PRESENT,
    unit: str | None = None,
) -> ScalarMeasurement:
    return ScalarMeasurement(
        name=name,
        analysis=analysis,
        status=status,
        value=value,
        unit=unit,
        source="log",
    )


def raw_case(
    *measurements: ScalarMeasurement,
    execution_succeeded: bool = True,
    case_name: str = "case_1",
) -> RawSimulationCaseResult:
    grouped: dict[str, list[ScalarMeasurement]] = {}
    for item in measurements:
        grouped.setdefault(item.analysis, []).append(item)

    analyses = tuple(
        RawAnalysisResult(
            analysis=analysis,
            status=AnalysisStatus.SUCCEEDED,
            converged=True,
            measurements=tuple(items),
        )
        for analysis, items in grouped.items()
    )
    return RawSimulationCaseResult(
        case_name=case_name,
        execution_succeeded=execution_succeeded,
        analyses=analyses,
    )


def test_greater_than_or_equal_rule_passes():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="minimum_gain",
                measurement="gain_db",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=69.5,
                unit="dB",
            ),
        )
    )

    result = engine.screen_case(
        raw_case(measurement("gain_db", 72.0, unit="dB"))
    )

    assert result.outcome is ScreeningOutcome.PASS
    assert result.rules[0].actual_value == 72.0


def test_failed_rule_makes_case_fail():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="minimum_phase_margin",
                measurement="phase_margin_deg",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=60.0,
            ),
        )
    )

    result = engine.screen_case(
        raw_case(measurement("phase_margin_deg", 25.0))
    )

    assert result.outcome is ScreeningOutcome.FAIL
    assert result.failed_rule_count == 1


def test_required_missing_measurement_is_unknown():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="minimum_ugb",
                measurement="ugb_hz",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=5e6,
            ),
        )
    )

    result = engine.screen_case(
        raw_case(
            measurement(
                "ugb_hz",
                None,
                status=MeasurementStatus.MISSING,
            )
        )
    )

    assert result.outcome is ScreeningOutcome.UNKNOWN
    assert result.unknown_rule_count == 1


def test_optional_missing_measurement_does_not_block_pass():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="optional_power",
                measurement="power_w",
                analysis="dc",
                operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
                threshold=2e-3,
                required=False,
            ),
        )
    )

    result = engine.screen_case(
        raw_case(
            measurement(
                "power_w",
                None,
                analysis="dc",
                status=MeasurementStatus.MISSING,
            )
        )
    )

    assert result.outcome is ScreeningOutcome.PASS
    assert result.rules[0].outcome is ScreeningOutcome.PASS


def test_tolerance_is_applied_to_minimum_rule():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="minimum_gain",
                measurement="gain_db",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=70.0,
                tolerance=0.1,
            ),
        )
    )

    result = engine.screen_case(
        raw_case(measurement("gain_db", 69.95))
    )

    assert result.outcome is ScreeningOutcome.PASS


def test_between_inclusive_rule():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="output_window",
                measurement="vout_dc",
                analysis="dc",
                operator=ComparisonOperator.BETWEEN_INCLUSIVE,
                lower=0.5,
                upper=2.0,
                unit="V",
            ),
        )
    )

    result = engine.screen_case(
        raw_case(measurement("vout_dc", 1.25, analysis="dc"))
    )

    assert result.outcome is ScreeningOutcome.PASS


def test_explicit_failure_has_priority_over_unknown():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="minimum_gain",
                measurement="gain_db",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=70.0,
            ),
            SpecificationRule(
                name="minimum_ugb",
                measurement="ugb_hz",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=5e6,
            ),
        )
    )

    result = engine.screen_case(
        raw_case(
            measurement("gain_db", 60.0),
            measurement(
                "ugb_hz",
                None,
                status=MeasurementStatus.MISSING,
            ),
        )
    )

    assert result.outcome is ScreeningOutcome.FAIL
    assert result.failed_rule_count == 1
    assert result.unknown_rule_count == 1


def test_failed_execution_without_rule_failure_is_unknown():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="minimum_gain",
                measurement="gain_db",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=70.0,
            ),
        )
    )

    result = engine.screen_case(
        raw_case(
            measurement("gain_db", 72.0),
            execution_succeeded=False,
        )
    )

    assert result.outcome is ScreeningOutcome.UNKNOWN


def test_screen_many_summarizes_outcomes():
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="minimum_gain",
                measurement="gain_db",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=70.0,
            ),
        )
    )

    summary = engine.screen_many(
        (
            raw_case(
                measurement("gain_db", 72.0),
                case_name="pass_case",
            ),
            raw_case(
                measurement("gain_db", 60.0),
                case_name="fail_case",
            ),
        )
    )

    assert summary.passed_case_count == 1
    assert summary.failed_case_count == 1
    assert summary.unknown_case_count == 0


def test_screening_result_preserves_raw_result_identity():
    raw = raw_case(measurement("gain_db", 72.0))
    engine = SpecificationScreeningEngine(
        (
            SpecificationRule(
                name="minimum_gain",
                measurement="gain_db",
                analysis="ac",
                operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                threshold=70.0,
            ),
        )
    )

    screened = engine.screen_case(raw)

    assert screened.raw_result is raw

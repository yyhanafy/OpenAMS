"""End-to-end simulation orchestration without collapsing layer boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .results import (
    MeasurementDeclaration,
    NgspiceRawResultParser,
    RawSimulationCaseResult,
)
from .screening import (
    ScreeningSummary,
    SpecificationRule,
    SpecificationScreeningEngine,
)


class WorkflowError(RuntimeError):
    """Base error for simulation workflow orchestration."""


class WorkflowStage(str, Enum):
    EXECUTION = "execution"
    PARSING = "parsing"
    SCREENING = "screening"


@dataclass(frozen=True)
class WorkflowDiagnostic:
    """Structured diagnostic emitted by one workflow stage."""

    stage: WorkflowStage
    message: str
    case_name: str | None = None
    exception_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "message": self.message,
            "case_name": self.case_name,
            "exception_type": self.exception_type,
        }


@dataclass(frozen=True)
class SimulationWorkflowResult:
    """Immutable record preserving every intermediate workflow artifact."""

    request: Any
    execution_result: Any
    raw_results: tuple[RawSimulationCaseResult, ...]
    screening_summary: ScreeningSummary
    diagnostics: tuple[WorkflowDiagnostic, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return (
            not self.diagnostics
            and self.screening_summary.failed_case_count == 0
            and self.screening_summary.unknown_case_count == 0
        )

    def to_dict(self) -> dict[str, Any]:
        request_payload = (
            self.request.to_dict()
            if hasattr(self.request, "to_dict")
            else repr(self.request)
        )
        execution_payload = (
            self.execution_result.to_dict()
            if hasattr(self.execution_result, "to_dict")
            else repr(self.execution_result)
        )
        return {
            "succeeded": self.succeeded,
            "request": request_payload,
            "execution_result": execution_payload,
            "raw_results": [item.to_dict() for item in self.raw_results],
            "screening_summary": self.screening_summary.to_dict(),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "provenance": dict(self.provenance),
        }


class SimulationRunnerProtocol(Protocol):
    def run(self, request: Any) -> Any:
        ...


class RawResultParserProtocol(Protocol):
    def parse_case(
        self,
        case_result: Any,
        declarations: Iterable[MeasurementDeclaration],
    ) -> RawSimulationCaseResult:
        ...


class SimulationWorkflow:
    """Compose execution, parsing, and screening without merging concerns."""

    def __init__(
        self,
        *,
        runner: SimulationRunnerProtocol,
        parser: RawResultParserProtocol,
        declarations: Iterable[MeasurementDeclaration],
        rules: Iterable[SpecificationRule],
    ) -> None:
        self.runner = runner
        self.parser = parser
        self.declarations = tuple(declarations)
        self.rules = tuple(rules)

        if not self.declarations:
            raise ValueError("at least one measurement declaration is required")
        if not self.rules:
            raise ValueError("at least one specification rule is required")

        declared = {(item.analysis, item.name) for item in self.declarations}
        missing = sorted(
            {
                (rule.analysis, rule.measurement)
                for rule in self.rules
                if (rule.analysis, rule.measurement) not in declared
            }
        )
        if missing:
            formatted = ", ".join(f"{analysis}.{name}" for analysis, name in missing)
            raise ValueError(
                "specification rules reference undeclared measurements: "
                + formatted
            )

    def run(self, request: Any) -> SimulationWorkflowResult:
        diagnostics: list[WorkflowDiagnostic] = []

        try:
            execution_result = self.runner.run(request)
        except Exception as exc:
            raise WorkflowError(
                f"simulation execution failed before producing a result: {exc}"
            ) from exc

        case_results = tuple(getattr(execution_result, "cases", ()) or ())
        raw_results: list[RawSimulationCaseResult] = []

        for case_result in case_results:
            case_name = str(getattr(case_result, "case_name", "unknown_case"))
            try:
                parsed = self.parser.parse_case(
                    case_result,
                    self.declarations,
                )
            except Exception as exc:
                diagnostics.append(
                    WorkflowDiagnostic(
                        stage=WorkflowStage.PARSING,
                        case_name=case_name,
                        message=str(exc),
                        exception_type=type(exc).__name__,
                    )
                )
                continue
            raw_results.append(parsed)

        screening_engine = SpecificationScreeningEngine(self.rules)
        screening_summary = screening_engine.screen_many(raw_results)

        return SimulationWorkflowResult(
            request=request,
            execution_result=execution_result,
            raw_results=tuple(raw_results),
            screening_summary=screening_summary,
            diagnostics=tuple(diagnostics),
            provenance={
                "requested_case_count": len(case_results),
                "parsed_case_count": len(raw_results),
                "measurement_declaration_count": len(self.declarations),
                "specification_rule_count": len(self.rules),
            },
        )


def build_ngspice_workflow(
    *,
    runner: SimulationRunnerProtocol,
    declarations: Iterable[MeasurementDeclaration],
    rules: Iterable[SpecificationRule],
) -> SimulationWorkflow:
    """Convenience factory using the canonical ngspice raw-result parser."""

    return SimulationWorkflow(
        runner=runner,
        parser=NgspiceRawResultParser(),
        declarations=declarations,
        rules=rules,
    )

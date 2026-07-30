"""Backend-neutral raw simulation result models and parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


class ResultParsingError(RuntimeError):
    """Base error for raw simulation result parsing."""


class MeasurementStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    MALFORMED = "malformed"


class AnalysisStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class MeasurementDeclaration:
    """One scalar measurement expected from a simulator artifact."""

    name: str
    analysis: str
    source: str = "log"
    required: bool = True
    aliases: tuple[str, ...] = ()
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("measurement name must be non-empty")
        if not self.analysis.strip():
            raise ValueError("analysis must be non-empty")
        if not self.source.strip():
            raise ValueError("source must be non-empty")
        object.__setattr__(self, "aliases", tuple(str(v) for v in self.aliases))


@dataclass(frozen=True)
class ScalarMeasurement:
    """Backend-neutral scalar measurement record."""

    name: str
    analysis: str
    status: MeasurementStatus
    value: float | None
    unit: str | None
    source: str
    raw_text: str | None = None
    diagnostic: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.status is MeasurementStatus.PRESENT and self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "analysis": self.analysis,
            "status": self.status.value,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "raw_text": self.raw_text,
            "diagnostic": self.diagnostic,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class RawAnalysisResult:
    """Raw result for one requested analysis."""

    analysis: str
    status: AnalysisStatus
    converged: bool | None
    measurements: tuple[ScalarMeasurement, ...]
    diagnostics: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return (
            self.status is AnalysisStatus.SUCCEEDED
            and all(item.available for item in self.measurements)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis,
            "status": self.status.value,
            "converged": self.converged,
            "measurements": [m.to_dict() for m in self.measurements],
            "diagnostics": list(self.diagnostics),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class RawSimulationCaseResult:
    """Backend-neutral parsed result for one simulator case."""

    case_name: str
    execution_succeeded: bool
    analyses: tuple[RawAnalysisResult, ...]
    diagnostics: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.execution_succeeded and all(
            analysis.status is AnalysisStatus.SUCCEEDED for analysis in self.analyses
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_name": self.case_name,
            "execution_succeeded": self.execution_succeeded,
            "succeeded": self.succeeded,
            "analyses": [a.to_dict() for a in self.analyses],
            "diagnostics": list(self.diagnostics),
            "provenance": dict(self.provenance),
        }


_NUMBER = re.compile(
    r"""
    (?P<number>
        [+-]?
        (?:
            (?:\d+(?:\.\d*)?)
            |
            (?:\.\d+)
        )
        (?:[eE][+-]?\d+)?
    )
    """,
    re.VERBOSE,
)


def parse_finite_float(text: str) -> float:
    """Parse one finite scalar without accepting trailing garbage."""

    candidate = text.strip()
    if not _NUMBER.fullmatch(candidate):
        raise ValueError(f"not a scalar number: {text!r}")
    value = float(candidate)
    if not math.isfinite(value):
        raise ValueError(f"non-finite scalar: {text!r}")
    return value


def _measurement_patterns(names: Sequence[str]) -> tuple[re.Pattern[str], ...]:
    escaped = "|".join(re.escape(name) for name in names)
    return (
        re.compile(
            rf"(?im)^\s*(?P<name>{escaped})\s*=\s*(?P<value>[^\s,;]+)"
        ),
        re.compile(
            rf"(?im)^\s*(?P<name>{escaped})\s*:\s*(?P<value>[^\s,;]+)"
        ),
    )


def parse_declared_measurement(
    text: str,
    declaration: MeasurementDeclaration,
    *,
    source_path: str,
) -> ScalarMeasurement:
    names = (declaration.name, *declaration.aliases)
    matches: list[re.Match[str]] = []
    for pattern in _measurement_patterns(names):
        matches.extend(pattern.finditer(text))

    if not matches:
        return ScalarMeasurement(
            name=declaration.name,
            analysis=declaration.analysis,
            status=MeasurementStatus.MISSING,
            value=None,
            unit=declaration.unit,
            source=declaration.source,
            diagnostic="declared measurement was not found",
            provenance={"source_path": source_path, "aliases": list(declaration.aliases)},
        )

    match = matches[-1]
    raw = match.group("value")
    try:
        value = parse_finite_float(raw)
    except ValueError as exc:
        return ScalarMeasurement(
            name=declaration.name,
            analysis=declaration.analysis,
            status=MeasurementStatus.MALFORMED,
            value=None,
            unit=declaration.unit,
            source=declaration.source,
            raw_text=raw,
            diagnostic=str(exc),
            provenance={
                "source_path": source_path,
                "matched_name": match.group("name"),
                "match_count": len(matches),
            },
        )

    return ScalarMeasurement(
        name=declaration.name,
        analysis=declaration.analysis,
        status=MeasurementStatus.PRESENT,
        value=value,
        unit=declaration.unit,
        source=declaration.source,
        raw_text=raw,
        provenance={
            "source_path": source_path,
            "matched_name": match.group("name"),
            "match_count": len(matches),
        },
    )


def detect_ngspice_convergence(text: str) -> tuple[bool | None, tuple[str, ...]]:
    """Infer convergence from high-signal ngspice diagnostics."""

    lowered = text.lower()
    failure_markers = (
        "timestep too small",
        "singular matrix",
        "doAnalyses: operating point failed".lower(),
        "dc solution failed",
        "no convergence",
        "iteration limit reached",
    )
    found = tuple(marker for marker in failure_markers if marker in lowered)
    if found:
        return False, tuple(f"ngspice convergence marker: {item}" for item in found)

    success_markers = (
        "operating point",
        "transient analysis",
        "ac analysis",
        "measure",
    )
    if any(marker in lowered for marker in success_markers):
        return True, ()
    return None, ("no explicit convergence marker was found",)


class NgspiceRawResultParser:
    """Parse ngspice execution artifacts into backend-neutral raw results."""

    def parse_case(
        self,
        case_result: Any,
        declarations: Iterable[MeasurementDeclaration],
    ) -> RawSimulationCaseResult:
        case_name = str(getattr(case_result, "case_name", "unknown_case"))
        execution_succeeded = bool(getattr(case_result, "succeeded", False))
        case_directory = Path(str(getattr(case_result, "case_directory")))

        declarations = tuple(declarations)
        by_analysis: dict[str, list[MeasurementDeclaration]] = {}
        for declaration in declarations:
            by_analysis.setdefault(declaration.analysis, []).append(declaration)

        source_cache: dict[str, tuple[str, str]] = {}
        case_diagnostics: list[str] = []
        analyses: list[RawAnalysisResult] = []

        for analysis_name, analysis_declarations in by_analysis.items():
            measurements: list[ScalarMeasurement] = []
            analysis_text_parts: list[str] = []
            analysis_diagnostics: list[str] = []

            for declaration in analysis_declarations:
                if declaration.source not in source_cache:
                    source_path = self._resolve_source(case_directory, declaration.source)
                    if source_path is None:
                        source_cache[declaration.source] = ("", "")
                    else:
                        try:
                            source_cache[declaration.source] = (
                                source_path.read_text(encoding="utf-8", errors="replace"),
                                str(source_path),
                            )
                        except OSError as exc:
                            source_cache[declaration.source] = ("", str(source_path))
                            case_diagnostics.append(
                                f"could not read {source_path}: {exc}"
                            )

                text, source_path = source_cache[declaration.source]
                if text:
                    analysis_text_parts.append(text)

                if not source_path:
                    measurement = ScalarMeasurement(
                        name=declaration.name,
                        analysis=declaration.analysis,
                        status=MeasurementStatus.MISSING,
                        value=None,
                        unit=declaration.unit,
                        source=declaration.source,
                        diagnostic="declared source artifact does not exist",
                        provenance={"case_directory": str(case_directory)},
                    )
                else:
                    measurement = parse_declared_measurement(
                        text,
                        declaration,
                        source_path=source_path,
                    )
                measurements.append(measurement)

            combined_text = "\n".join(analysis_text_parts)
            converged, convergence_diagnostics = detect_ngspice_convergence(
                combined_text
            )
            analysis_diagnostics.extend(convergence_diagnostics)

            required_bad = any(
                declaration.required
                and measurement.status is not MeasurementStatus.PRESENT
                for declaration, measurement in zip(
                    analysis_declarations, measurements, strict=True
                )
            )

            if not execution_succeeded:
                status = AnalysisStatus.NOT_RUN
                analysis_diagnostics.append("simulator execution did not succeed")
            elif converged is False:
                status = AnalysisStatus.FAILED
            elif required_bad:
                status = AnalysisStatus.INCOMPLETE
            else:
                status = AnalysisStatus.SUCCEEDED

            analyses.append(
                RawAnalysisResult(
                    analysis=analysis_name,
                    status=status,
                    converged=converged,
                    measurements=tuple(measurements),
                    diagnostics=tuple(analysis_diagnostics),
                    provenance={
                        "case_name": case_name,
                        "case_directory": str(case_directory),
                    },
                )
            )

        return RawSimulationCaseResult(
            case_name=case_name,
            execution_succeeded=execution_succeeded,
            analyses=tuple(analyses),
            diagnostics=tuple(case_diagnostics),
            provenance={
                "case_directory": str(case_directory),
                "return_code": getattr(case_result, "return_code", None),
                "timed_out": bool(getattr(case_result, "timed_out", False)),
            },
        )

    @staticmethod
    def _resolve_source(case_directory: Path, source: str) -> Path | None:
        aliases = {
            "log": "ngspice.log",
            "stdout": "stdout.txt",
            "stderr": "stderr.txt",
        }
        filename = aliases.get(source, source)
        path = case_directory / filename
        return path if path.is_file() else None

"""Persistence for complete simulation workflow results."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .screening import ScreeningOutcome
from .workflow import SimulationWorkflowResult


SCHEMA_VERSION = "openams.simulation_workflow.v1"


class PersistenceError(RuntimeError):
    """Base error for workflow persistence."""


@dataclass(frozen=True)
class PersistedWorkflowArtifacts:
    """Paths written for one workflow persistence operation."""

    directory: Path
    workflow_json: Path
    summary_csv: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "directory": str(self.directory),
            "workflow_json": str(self.workflow_json),
            "summary_csv": str(self.summary_csv),
        }


def _relativize_path(value: Any, base_directory: Path) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _relativize_path(item, base_directory)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [_relativize_path(item, base_directory) for item in value]

    if isinstance(value, tuple):
        return [_relativize_path(item, base_directory) for item in value]

    if isinstance(value, str):
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                return str(candidate.relative_to(base_directory))
            except ValueError:
                return value

    return value


def canonical_workflow_payload(
    result: SimulationWorkflowResult,
    *,
    output_directory: Path,
) -> dict[str, Any]:
    """Build deterministic, schema-versioned workflow JSON payload."""

    payload = result.to_dict()
    payload = _relativize_path(payload, output_directory.resolve())

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_root": ".",
        "workflow": payload,
    }


def write_canonical_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )
    path.write_text(text + "\n", encoding="utf-8")


def _measurement_index(case_payload: Mapping[str, Any]) -> dict[tuple[str, str], Any]:
    index: dict[tuple[str, str], Any] = {}
    raw_result = case_payload.get("raw_result", {})
    for analysis in raw_result.get("analyses", []):
        analysis_name = analysis.get("analysis")
        for measurement in analysis.get("measurements", []):
            index[(analysis_name, measurement.get("name"))] = measurement.get("value")
    return index


def deterministic_summary_rows(
    result: SimulationWorkflowResult,
) -> tuple[dict[str, Any], ...]:
    """Flatten screened cases into deterministic CSV rows."""

    rows: list[dict[str, Any]] = []

    for case in sorted(
        result.screening_summary.cases,
        key=lambda item: item.case_name,
    ):
        payload = case.to_dict()
        measurements = _measurement_index(payload)

        base = {
            "case_name": case.case_name,
            "case_outcome": case.outcome.value,
            "case_passed": str(case.passed).lower(),
            "failed_rule_count": case.failed_rule_count,
            "unknown_rule_count": case.unknown_rule_count,
            "execution_succeeded": str(
                case.raw_result.execution_succeeded
            ).lower(),
        }

        if not case.rules:
            rows.append(
                {
                    **base,
                    "rule_name": "",
                    "analysis": "",
                    "measurement": "",
                    "rule_outcome": "",
                    "actual_value": "",
                    "operator": "",
                    "threshold": "",
                    "lower": "",
                    "upper": "",
                    "tolerance": "",
                    "unit": "",
                    "diagnostic": "",
                }
            )
            continue

        for rule in sorted(case.rules, key=lambda item: item.rule_name):
            expected = dict(rule.expected)
            rows.append(
                {
                    **base,
                    "rule_name": rule.rule_name,
                    "analysis": rule.analysis,
                    "measurement": rule.measurement,
                    "rule_outcome": rule.outcome.value,
                    "actual_value": (
                        ""
                        if rule.actual_value is None
                        else repr(rule.actual_value)
                    ),
                    "operator": expected.get("operator", ""),
                    "threshold": expected.get("threshold", ""),
                    "lower": expected.get("lower", ""),
                    "upper": expected.get("upper", ""),
                    "tolerance": expected.get("tolerance", ""),
                    "unit": rule.unit or "",
                    "diagnostic": rule.diagnostic or "",
                }
            )

    return tuple(rows)


SUMMARY_FIELDNAMES = (
    "case_name",
    "case_outcome",
    "case_passed",
    "failed_rule_count",
    "unknown_rule_count",
    "execution_succeeded",
    "rule_name",
    "analysis",
    "measurement",
    "rule_outcome",
    "actual_value",
    "operator",
    "threshold",
    "lower",
    "upper",
    "tolerance",
    "unit",
    "diagnostic",
)


def write_summary_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=SUMMARY_FIELDNAMES,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in SUMMARY_FIELDNAMES})


class SimulationWorkflowPersistence:
    """Persist and reload complete workflow artifacts."""

    def persist(
        self,
        result: SimulationWorkflowResult,
        output_directory: str | Path,
    ) -> PersistedWorkflowArtifacts:
        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)

        workflow_json = directory / "workflow_result.json"
        summary_csv = directory / "screening_summary.csv"

        payload = canonical_workflow_payload(
            result,
            output_directory=directory,
        )
        write_canonical_json(workflow_json, payload)
        write_summary_csv(
            summary_csv,
            deterministic_summary_rows(result),
        )

        return PersistedWorkflowArtifacts(
            directory=directory,
            workflow_json=workflow_json,
            summary_csv=summary_csv,
        )

    def load_payload(
        self,
        workflow_json: str | Path,
    ) -> dict[str, Any]:
        path = Path(workflow_json)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PersistenceError(
                f"could not load workflow JSON {path}: {exc}"
            ) from exc

        version = payload.get("schema_version")
        if version != SCHEMA_VERSION:
            raise PersistenceError(
                f"unsupported workflow schema version: {version!r}"
            )
        if "workflow" not in payload:
            raise PersistenceError("workflow JSON is missing 'workflow' payload")
        return payload

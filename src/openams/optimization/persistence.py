"""Persistence for candidate evaluations and optimizer feedback."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .evaluation import CandidateEvaluationSummary


SCHEMA_VERSION = "openams.candidate_evaluation.v1"


class EvaluationPersistenceError(RuntimeError):
    """Base error for candidate-evaluation persistence."""


@dataclass(frozen=True)
class PersistedEvaluationArtifacts:
    """Files written for one evaluation persistence operation."""

    directory: Path
    evaluation_json: Path
    ranking_csv: Path
    objective_components_csv: Path
    optimizer_feedback_json: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "directory": str(self.directory),
            "evaluation_json": str(self.evaluation_json),
            "ranking_csv": str(self.ranking_csv),
            "objective_components_csv": str(self.objective_components_csv),
            "optimizer_feedback_json": str(self.optimizer_feedback_json),
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


def canonical_evaluation_payload(
    summary: CandidateEvaluationSummary,
    *,
    output_directory: Path,
    workflow_result_path: str | Path | None = None,
) -> dict[str, Any]:
    workflow_link: str | None = None
    if workflow_result_path is not None:
        workflow_link = str(workflow_result_path)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_root": ".",
        "workflow_result": workflow_link,
        "evaluation": summary.to_dict(),
    }
    return _relativize_path(payload, output_directory.resolve())


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


RANKING_FIELDS = (
    "rank",
    "candidate_id",
    "state",
    "aggregate_score",
    "rankable",
    "failure_reasons",
    "unknown_reasons",
)


def ranking_rows(
    summary: CandidateEvaluationSummary,
) -> tuple[dict[str, Any], ...]:
    rows = []
    for ranked in summary.ranking:
        evaluation = ranked.evaluation
        rows.append(
            {
                "rank": ranked.rank,
                "candidate_id": evaluation.candidate_id,
                "state": evaluation.state.value,
                "aggregate_score": (
                    ""
                    if evaluation.aggregate_score is None
                    else repr(evaluation.aggregate_score)
                ),
                "rankable": str(evaluation.rankable).lower(),
                "failure_reasons": "|".join(evaluation.failure_reasons),
                "unknown_reasons": "|".join(evaluation.unknown_reasons),
            }
        )
    return tuple(rows)


OBJECTIVE_FIELDS = (
    "candidate_id",
    "candidate_state",
    "objective_name",
    "analysis",
    "measurement",
    "direction",
    "status",
    "raw_value",
    "normalized_value",
    "weighted_value",
    "weight",
    "unit",
    "diagnostic",
)


def objective_component_rows(
    summary: CandidateEvaluationSummary,
) -> tuple[dict[str, Any], ...]:
    rows = []
    for evaluation in sorted(
        summary.evaluations,
        key=lambda item: item.candidate_id,
    ):
        for component in sorted(
            evaluation.objectives,
            key=lambda item: item.name,
        ):
            rows.append(
                {
                    "candidate_id": evaluation.candidate_id,
                    "candidate_state": evaluation.state.value,
                    "objective_name": component.name,
                    "analysis": component.analysis,
                    "measurement": component.measurement,
                    "direction": component.direction.value,
                    "status": component.status,
                    "raw_value": (
                        ""
                        if component.raw_value is None
                        else repr(component.raw_value)
                    ),
                    "normalized_value": (
                        ""
                        if component.normalized_value is None
                        else repr(component.normalized_value)
                    ),
                    "weighted_value": (
                        ""
                        if component.weighted_value is None
                        else repr(component.weighted_value)
                    ),
                    "weight": repr(component.weight),
                    "unit": component.unit or "",
                    "diagnostic": component.diagnostic or "",
                }
            )
    return tuple(rows)


def write_csv(
    path: Path,
    *,
    fieldnames: tuple[str, ...],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {field: row.get(field, "") for field in fieldnames}
            )


def optimizer_feedback_payload(
    summary: CandidateEvaluationSummary,
) -> dict[str, Any]:
    feedback = [
        evaluation.optimizer_feedback().to_dict()
        for evaluation in sorted(
            summary.evaluations,
            key=lambda item: item.candidate_id,
        )
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "feedback": feedback,
    }


class CandidateEvaluationPersistence:
    """Persist and reload candidate evaluations deterministically."""

    def persist(
        self,
        summary: CandidateEvaluationSummary,
        output_directory: str | Path,
        *,
        workflow_result_path: str | Path | None = None,
    ) -> PersistedEvaluationArtifacts:
        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)

        evaluation_json = directory / "candidate_evaluation.json"
        ranking_csv = directory / "candidate_ranking.csv"
        objective_components_csv = directory / "objective_components.csv"
        optimizer_feedback_json = directory / "optimizer_feedback.json"

        write_canonical_json(
            evaluation_json,
            canonical_evaluation_payload(
                summary,
                output_directory=directory,
                workflow_result_path=workflow_result_path,
            ),
        )
        write_csv(
            ranking_csv,
            fieldnames=RANKING_FIELDS,
            rows=ranking_rows(summary),
        )
        write_csv(
            objective_components_csv,
            fieldnames=OBJECTIVE_FIELDS,
            rows=objective_component_rows(summary),
        )
        write_canonical_json(
            optimizer_feedback_json,
            optimizer_feedback_payload(summary),
        )

        return PersistedEvaluationArtifacts(
            directory=directory,
            evaluation_json=evaluation_json,
            ranking_csv=ranking_csv,
            objective_components_csv=objective_components_csv,
            optimizer_feedback_json=optimizer_feedback_json,
        )

    def load_payload(
        self,
        evaluation_json: str | Path,
    ) -> dict[str, Any]:
        path = Path(evaluation_json)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationPersistenceError(
                f"could not load candidate evaluation JSON {path}: {exc}"
            ) from exc

        version = payload.get("schema_version")
        if version != SCHEMA_VERSION:
            raise EvaluationPersistenceError(
                f"unsupported candidate evaluation schema version: {version!r}"
            )
        if "evaluation" not in payload:
            raise EvaluationPersistenceError(
                "candidate evaluation JSON is missing 'evaluation'"
            )
        return payload

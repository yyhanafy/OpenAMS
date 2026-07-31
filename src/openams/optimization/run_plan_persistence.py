"""Persistence and reconstruction for optimization run plans."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .run_plan import (
    OptimizationRunPlan,
    ResolutionState,
)
from .session import OptimizationRoute


class RunPlanPersistenceError(RuntimeError):
    """Raised when a run-plan artifact is invalid or cannot be reconstructed."""


@dataclass(frozen=True)
class OptimizationRunPlanArtifacts:
    """Paths produced by run-plan persistence."""

    run_plan_json: Path


class OptimizationRunPlanPersistence:
    """Persist and reconstruct ``OptimizationRunPlan`` artifacts."""

    SCHEMA_VERSION = 1
    DEFAULT_FILENAME = "optimization_run_plan.json"

    def persist(
        self,
        plan: OptimizationRunPlan,
        output_directory: str | Path,
        *,
        session_artifact_path: str | Path | None = None,
    ) -> OptimizationRunPlanArtifacts:
        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / self.DEFAULT_FILENAME
        payload = self._payload(
            plan,
            session_artifact_path=session_artifact_path,
        )
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return OptimizationRunPlanArtifacts(run_plan_json=path)

    def load(
        self,
        path: str | Path,
    ) -> OptimizationRunPlan:
        artifact_path = Path(path)
        try:
            payload = json.loads(
                artifact_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RunPlanPersistenceError(
                f"failed to read run-plan artifact: {artifact_path}"
            ) from exc

        return self.from_payload(payload)

    def from_payload(
        self,
        payload: Mapping[str, Any],
    ) -> OptimizationRunPlan:
        schema_version = payload.get("schema_version")
        if schema_version != self.SCHEMA_VERSION:
            raise RunPlanPersistenceError(
                "unsupported run-plan schema_version: "
                f"{schema_version!r}"
            )

        plan_payload = payload.get("plan")
        if not isinstance(plan_payload, Mapping):
            raise RunPlanPersistenceError(
                "run-plan artifact is missing a 'plan' object"
            )

        try:
            route = OptimizationRoute(str(plan_payload["route"]))
            resolution_state = ResolutionState(
                str(plan_payload["resolution_state"])
            )
            reason_code = str(plan_payload["reason_code"])
            reason = str(plan_payload["reason"])
        except (KeyError, ValueError, TypeError) as exc:
            raise RunPlanPersistenceError(
                "run-plan artifact has invalid route-decision fields"
            ) from exc

        assignments_payload = plan_payload.get("assignments", [])
        if not isinstance(assignments_payload, list):
            raise RunPlanPersistenceError(
                "run-plan assignments must be a list"
            )
        assignments = tuple(
            {
                str(name): float(value)
                for name, value in sorted(dict(item).items())
            }
            for item in assignments_payload
        )

        bounds_payload = plan_payload.get("parameter_bounds", {})
        if not isinstance(bounds_payload, Mapping):
            raise RunPlanPersistenceError(
                "run-plan parameter_bounds must be an object"
            )
        parameter_bounds: dict[str, tuple[float, float]] = {}
        for name, bounds in bounds_payload.items():
            if not isinstance(bounds, Mapping):
                raise RunPlanPersistenceError(
                    f"bounds for {name!r} must be an object"
                )
            try:
                lower = float(bounds["lower"])
                upper = float(bounds["upper"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RunPlanPersistenceError(
                    f"invalid bounds for {name!r}"
                ) from exc
            parameter_bounds[str(name)] = (lower, upper)

        fixed_payload = plan_payload.get("fixed_parameters", {})
        metadata_payload = plan_payload.get("metadata", {})
        if not isinstance(fixed_payload, Mapping):
            raise RunPlanPersistenceError(
                "run-plan fixed_parameters must be an object"
            )
        if not isinstance(metadata_payload, Mapping):
            raise RunPlanPersistenceError(
                "run-plan metadata must be an object"
            )

        plan = OptimizationRunPlan(
            route=route,
            resolution_state=resolution_state,
            reason_code=reason_code,
            reason=reason,
            assignments=assignments,
            parameter_bounds=parameter_bounds,
            fixed_parameters={
                str(name): float(value)
                for name, value in sorted(fixed_payload.items())
            },
            metadata=dict(metadata_payload),
        )
        self._validate_reconstructed_plan(plan)
        return plan

    def link_session_artifact(
        self,
        run_plan_path: str | Path,
        session_artifact_path: str | Path,
    ) -> OptimizationRunPlanArtifacts:
        """Add or replace the forward session-artifact link."""

        path = Path(run_plan_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunPlanPersistenceError(
                f"failed to read run-plan artifact: {path}"
            ) from exc

        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise RunPlanPersistenceError(
                "cannot link session artifact to unsupported schema"
            )

        payload["links"] = {
            **dict(payload.get("links") or {}),
            "optimization_session": str(
                self._relative_or_absolute(
                    Path(session_artifact_path),
                    path.parent,
                )
            ),
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return OptimizationRunPlanArtifacts(run_plan_json=path)

    def read_session_artifact_link(
        self,
        run_plan_path: str | Path,
    ) -> Path | None:
        path = Path(run_plan_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunPlanPersistenceError(
                f"failed to read run-plan artifact: {path}"
            ) from exc

        links = payload.get("links") or {}
        value = links.get("optimization_session")
        if value is None:
            return None

        linked = Path(str(value))
        return linked if linked.is_absolute() else path.parent / linked

    @classmethod
    def _payload(
        cls,
        plan: OptimizationRunPlan,
        *,
        session_artifact_path: str | Path | None,
    ) -> dict[str, Any]:
        links: dict[str, str] = {}
        if session_artifact_path is not None:
            links["optimization_session"] = str(session_artifact_path)

        return {
            "schema_version": cls.SCHEMA_VERSION,
            "artifact_type": "optimization_run_plan",
            "plan": plan.to_dict(),
            "links": links,
        }

    @staticmethod
    def _relative_or_absolute(
        target: Path,
        base: Path,
    ) -> Path:
        try:
            return target.relative_to(base)
        except ValueError:
            return target

    @staticmethod
    def _validate_reconstructed_plan(
        plan: OptimizationRunPlan,
    ) -> None:
        if plan.route is OptimizationRoute.DIRECT_SIMULATION:
            if not plan.assignments:
                raise RunPlanPersistenceError(
                    "direct run plan has no assignments"
                )
            if plan.parameter_bounds:
                raise RunPlanPersistenceError(
                    "direct run plan contains parameter bounds"
                )
        elif plan.route is OptimizationRoute.CONTRACT_SEARCH:
            if not plan.parameter_bounds:
                raise RunPlanPersistenceError(
                    "contract-search run plan has no parameter bounds"
                )

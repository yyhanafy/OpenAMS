"""Top-level launch manifest for one OpenAMS optimization execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping


class OptimizationLaunchStatus(str, Enum):
    """Top-level launch status."""

    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LaunchManifestError(RuntimeError):
    """Raised when a launch manifest cannot be persisted or reconstructed."""


@dataclass(frozen=True)
class OptimizationLaunchArtifacts:
    """Primary artifact paths for one launch."""

    run_plan: Path
    session: Path | None = None
    evaluation: Path | None = None
    workflow: Path | None = None

    def to_dict(
        self,
        *,
        base_directory: Path | None = None,
    ) -> dict[str, str | None]:
        return {
            "run_plan": self._serialize_path(
                self.run_plan,
                base_directory,
            ),
            "session": self._serialize_optional_path(
                self.session,
                base_directory,
            ),
            "evaluation": self._serialize_optional_path(
                self.evaluation,
                base_directory,
            ),
            "workflow": self._serialize_optional_path(
                self.workflow,
                base_directory,
            ),
        }

    @staticmethod
    def _serialize_optional_path(
        path: Path | None,
        base_directory: Path | None,
    ) -> str | None:
        if path is None:
            return None
        return OptimizationLaunchArtifacts._serialize_path(
            path,
            base_directory,
        )

    @staticmethod
    def _serialize_path(
        path: Path,
        base_directory: Path | None,
    ) -> str:
        if base_directory is not None:
            try:
                return str(path.relative_to(base_directory))
            except ValueError:
                pass
        return str(path)


@dataclass(frozen=True)
class OptimizationLaunchManifest:
    """Stable CLI-facing record for one optimization launch."""

    launch_id: str
    status: OptimizationLaunchStatus
    route: str
    reason_code: str
    artifacts: OptimizationLaunchArtifacts
    error: str | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.launch_id:
            raise ValueError("launch_id must not be empty")
        if not self.route:
            raise ValueError("route must not be empty")
        if not self.reason_code:
            raise ValueError("reason_code must not be empty")

        if (
            self.status is OptimizationLaunchStatus.FAILED
            and not self.error
        ):
            raise ValueError("failed launch requires an error message")
        if (
            self.status is not OptimizationLaunchStatus.FAILED
            and self.error is not None
        ):
            raise ValueError(
                "non-failed launch must not carry an error message"
            )

        object.__setattr__(
            self,
            "metadata",
            dict(self.metadata or {}),
        )

    def to_dict(
        self,
        *,
        base_directory: Path | None = None,
    ) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "status": self.status.value,
            "route": self.route,
            "reason_code": self.reason_code,
            "error": self.error,
            "artifacts": self.artifacts.to_dict(
                base_directory=base_directory
            ),
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class OptimizationLaunchManifestArtifacts:
    """Paths written by launch-manifest persistence."""

    manifest_json: Path


class OptimizationLaunchManifestPersistence:
    """Persist and load ``optimization_launch_manifest.json``."""

    SCHEMA_VERSION = 1
    DEFAULT_FILENAME = "optimization_launch_manifest.json"

    def persist(
        self,
        manifest: OptimizationLaunchManifest,
        output_directory: str | Path,
    ) -> OptimizationLaunchManifestArtifacts:
        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self.DEFAULT_FILENAME

        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "artifact_type": "optimization_launch_manifest",
            "launch": manifest.to_dict(
                base_directory=directory
            ),
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return OptimizationLaunchManifestArtifacts(
            manifest_json=path
        )

    def load(
        self,
        path: str | Path,
    ) -> OptimizationLaunchManifest:
        manifest_path = Path(path)
        try:
            payload = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise LaunchManifestError(
                f"failed to read launch manifest: {manifest_path}"
            ) from exc

        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise LaunchManifestError(
                "unsupported launch-manifest schema_version: "
                f"{payload.get('schema_version')!r}"
            )
        if (
            payload.get("artifact_type")
            != "optimization_launch_manifest"
        ):
            raise LaunchManifestError(
                "invalid launch-manifest artifact_type"
            )

        launch = payload.get("launch")
        if not isinstance(launch, Mapping):
            raise LaunchManifestError(
                "launch manifest is missing a 'launch' object"
            )

        artifacts_payload = launch.get("artifacts")
        if not isinstance(artifacts_payload, Mapping):
            raise LaunchManifestError(
                "launch manifest is missing artifact links"
            )

        base = manifest_path.parent
        run_plan = self._resolve_required_path(
            artifacts_payload.get("run_plan"),
            base,
            "run_plan",
        )
        artifacts = OptimizationLaunchArtifacts(
            run_plan=run_plan,
            session=self._resolve_optional_path(
                artifacts_payload.get("session"),
                base,
            ),
            evaluation=self._resolve_optional_path(
                artifacts_payload.get("evaluation"),
                base,
            ),
            workflow=self._resolve_optional_path(
                artifacts_payload.get("workflow"),
                base,
            ),
        )

        try:
            status = OptimizationLaunchStatus(
                str(launch["status"])
            )
            return OptimizationLaunchManifest(
                launch_id=str(launch["launch_id"]),
                status=status,
                route=str(launch["route"]),
                reason_code=str(launch["reason_code"]),
                error=launch.get("error"),
                artifacts=artifacts,
                metadata=dict(launch.get("metadata") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LaunchManifestError(
                "invalid launch-manifest fields"
            ) from exc

    @staticmethod
    def _resolve_required_path(
        value: Any,
        base: Path,
        field_name: str,
    ) -> Path:
        if value is None or str(value) == "":
            raise LaunchManifestError(
                f"launch manifest requires artifact link: {field_name}"
            )
        return OptimizationLaunchManifestPersistence._resolve_path(
            str(value),
            base,
        )

    @staticmethod
    def _resolve_optional_path(
        value: Any,
        base: Path,
    ) -> Path | None:
        if value is None:
            return None
        return OptimizationLaunchManifestPersistence._resolve_path(
            str(value),
            base,
        )

    @staticmethod
    def _resolve_path(
        value: str,
        base: Path,
    ) -> Path:
        path = Path(value)
        return path if path.is_absolute() else base / path

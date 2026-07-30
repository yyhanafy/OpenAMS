"""Concrete ngspice execution adapter.

This module intentionally performs only backend-specific preparation and
process execution.  It does not parse electrical metrics or decide whether a
circuit satisfies design specifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence


class NgspiceAdapterError(RuntimeError):
    """Base error raised by the concrete ngspice adapter."""


class NgspiceInputError(NgspiceAdapterError, ValueError):
    """Raised when a run request cannot be rendered safely."""


class NgspiceExecutionError(NgspiceAdapterError):
    """Raised when execution infrastructure fails before a result is available."""


class NgspiceCaseStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class NgspiceRunPolicy:
    """Execution policy for a batch of ngspice cases."""

    executable: str = "ngspice"
    timeout_seconds: float = 120.0
    extra_arguments: tuple[str, ...] = ()
    overwrite_existing: bool = False
    stop_on_failure: bool = False
    strict_template_rendering: bool = True
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("executable must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(
            self,
            "extra_arguments",
            tuple(str(item) for item in self.extra_arguments),
        )
        object.__setattr__(
            self,
            "environment",
            dict(sorted((str(k), str(v)) for k, v in self.environment.items())),
        )


@dataclass(frozen=True)
class NgspiceCaseResult:
    """Immutable execution record for one manifest case."""

    case_name: str
    status: NgspiceCaseStatus
    case_directory: str
    deck_path: str
    log_path: str
    stdout_path: str
    stderr_path: str
    command: tuple[str, ...]
    return_code: int | None
    timed_out: bool
    assignment_name: str | None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status is NgspiceCaseStatus.SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_name": self.case_name,
            "status": self.status.value,
            "case_directory": self.case_directory,
            "deck_path": self.deck_path,
            "log_path": self.log_path,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "command": list(self.command),
            "return_code": self.return_code,
            "timed_out": self.timed_out,
            "assignment_name": self.assignment_name,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class NgspiceRunResult:
    """Immutable result for a complete direct-simulation request."""

    backend: str
    output_directory: str
    cases: tuple[NgspiceCaseResult, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return bool(self.cases) and all(case.succeeded for case in self.cases)

    @property
    def failed_case_count(self) -> int:
        return sum(not case.succeeded for case in self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "output_directory": self.output_directory,
            "succeeded": self.succeeded,
            "case_count": len(self.cases),
            "failed_case_count": self.failed_case_count,
            "cases": [case.to_dict() for case in self.cases],
            "metadata": dict(self.metadata),
        }


CompletedProcessFactory = Callable[..., subprocess.CompletedProcess[str]]


_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9_.-]+")
_TOKEN_PATTERNS = (
    re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}"),
    re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}"),
    re.compile(r"@([A-Za-z_][A-Za-z0-9_.-]*)@"),
)


def _safe_component(value: str) -> str:
    candidate = _SAFE_COMPONENT.sub("_", value.strip()).strip("._")
    if not candidate:
        raise NgspiceInputError(f"unsafe or empty case name: {value!r}")
    return candidate


def _read_attr(obj: Any, *names: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _as_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    try:
        return {str(k): v for k, v in dict(value).items()}
    except Exception as exc:
        raise NgspiceInputError(f"{label} must be a mapping") from exc


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if hasattr(value, "__dict__"):
        return {
            str(k): _jsonable(v)
            for k, v in vars(value).items()
            if not str(k).startswith("_")
        }
    return value


def _format_parameter(value: Any) -> str:
    if isinstance(value, bool):
        raise NgspiceInputError("Boolean values are not valid ngspice parameters")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise NgspiceInputError("ngspice parameters must be finite")
        return repr(value)
    if isinstance(value, (int, str)):
        return str(value)
    raise NgspiceInputError(
        f"unsupported ngspice parameter type: {type(value).__name__}"
    )


def render_ngspice_template(
    template_text: str,
    parameters: Mapping[str, Any],
    *,
    strict: bool = True,
) -> str:
    """Render deterministic scalar tokens in a SPICE template.

    Supported token forms are ``{{NAME}}``, ``${NAME}``, and ``@NAME@``.
    This small renderer is deliberately not a general template language.
    """

    rendered = str(template_text)
    formatted = {str(k): _format_parameter(v) for k, v in parameters.items()}
    used: set[str] = set()

    for pattern in _TOKEN_PATTERNS:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in formatted:
                if strict:
                    raise NgspiceInputError(
                        f"template references missing parameter {name!r}"
                    )
                return match.group(0)
            used.add(name)
            return formatted[name]

        rendered = pattern.sub(replace, rendered)

    if strict:
        unresolved: set[str] = set()
        for pattern in _TOKEN_PATTERNS:
            unresolved.update(match.group(1) for match in pattern.finditer(rendered))
        if unresolved:
            raise NgspiceInputError(
                "unresolved template parameters: " + ", ".join(sorted(unresolved))
            )

    if rendered and not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


class NgspiceRunner:
    """Render and execute every case in a backend-neutral run request."""

    backend_name = "ngspice"

    def __init__(
        self,
        policy: NgspiceRunPolicy | None = None,
        *,
        process_runner: CompletedProcessFactory | None = None,
        executable_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self.policy = policy or NgspiceRunPolicy()
        self._process_runner = process_runner or subprocess.run
        self._executable_resolver = executable_resolver or shutil.which

    def run(
        self,
        request: Any,
        output_directory: str | os.PathLike[str] | None = None,
    ) -> NgspiceRunResult:
        manifest = _read_attr(request, "manifest", default=request)
        cases = tuple(_read_attr(manifest, "cases", default=()) or ())
        if not cases:
            raise NgspiceInputError("simulation request contains no cases")

        backend = _read_attr(manifest, "backend", default=self.backend_name)
        backend_value = getattr(backend, "value", backend)
        if str(backend_value).lower() not in {"ngspice", "simulationbackend.ngspice"}:
            raise NgspiceInputError(
                f"ngspice runner cannot execute backend {backend_value!r}"
            )

        root_value = output_directory or _read_attr(
            request,
            "output_directory",
            "output_dir",
            "work_directory",
            "work_root",
            default=None,
        )
        if root_value is None:
            raise NgspiceInputError(
                "output_directory is required either on the request or run()"
            )
        root = Path(root_value).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)

        executable = self._executable_resolver(self.policy.executable)
        if executable is None:
            raise NgspiceExecutionError(
                f"ngspice executable not found: {self.policy.executable}"
            )

        results: list[NgspiceCaseResult] = []
        seen_names: set[str] = set()

        for index, case in enumerate(cases):
            case_name = str(
                _read_attr(case, "case_name", "name", "case_id",
                           default=f"case_{index:06d}")
            )
            safe_name = _safe_component(case_name)
            if safe_name in seen_names:
                raise NgspiceInputError(f"duplicate case name: {safe_name}")
            seen_names.add(safe_name)

            case_result = self._run_case(
                case=case,
                case_name=safe_name,
                case_index=index,
                root=root,
                executable=executable,
                manifest=manifest,
            )
            results.append(case_result)
            if self.policy.stop_on_failure and not case_result.succeeded:
                break

        result = NgspiceRunResult(
            backend=self.backend_name,
            output_directory=str(root),
            cases=tuple(results),
            metadata={
                "requested_case_count": len(cases),
                "executed_case_count": len(results),
                "executable": executable,
            },
        )
        self._write_json(root / "run_result.json", result.to_dict())
        return result

    def _run_case(
        self,
        *,
        case: Any,
        case_name: str,
        case_index: int,
        root: Path,
        executable: str,
        manifest: Any,
    ) -> NgspiceCaseResult:
        case_dir = root / case_name
        if case_dir.exists():
            if not self.policy.overwrite_existing:
                raise NgspiceInputError(
                    f"case directory already exists: {case_dir}"
                )
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True)

        parameters = _as_mapping(
            _read_attr(
                case,
                "rendered_parameters",
                "parameters",
                "simulator_parameters",
                default={},
            ),
            label=f"parameters for {case_name}",
        )
        template_text, template_source = self._load_template(case, manifest)
        rendered = render_ngspice_template(
            template_text,
            parameters,
            strict=self.policy.strict_template_rendering,
        )

        deck_path = case_dir / "rendered.spice"
        log_path = case_dir / "ngspice.log"
        stdout_path = case_dir / "stdout.txt"
        stderr_path = case_dir / "stderr.txt"
        deck_path.write_text(rendered, encoding="utf-8")
        self._write_json(case_dir / "parameters.json", parameters)

        assignment_name = _read_attr(
            case, "assignment_name", "source_assignment_name", default=None
        )
        command = (
            executable,
            "-b",
            "-o",
            str(log_path),
            *self.policy.extra_arguments,
            str(deck_path),
        )

        case_record = {
            "case_name": case_name,
            "case_index": case_index,
            "assignment_name": assignment_name,
            "template_source": template_source,
            "command": list(command),
            "parameters": parameters,
            "analyses": _jsonable(
                _read_attr(case, "analyses", "requested_analyses", default=())
            ),
            "provenance": _jsonable(
                _read_attr(case, "provenance", "metadata", default={})
            ),
        }
        self._write_json(case_dir / "case.json", case_record)

        environment = os.environ.copy()
        environment.update(self.policy.environment)
        diagnostics: dict[str, Any] = {
            "template_source": template_source,
            "case_index": case_index,
        }

        try:
            completed = self._process_runner(
                list(command),
                cwd=str(case_dir),
                env=environment,
                text=True,
                capture_output=True,
                timeout=self.policy.timeout_seconds,
                check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            stdout_path.write_text(stdout, encoding="utf-8")
            stderr_path.write_text(stderr, encoding="utf-8")
            status = (
                NgspiceCaseStatus.SUCCEEDED
                if completed.returncode == 0
                else NgspiceCaseStatus.FAILED
            )
            result = NgspiceCaseResult(
                case_name=case_name,
                status=status,
                case_directory=str(case_dir),
                deck_path=str(deck_path),
                log_path=str(log_path),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                command=tuple(command),
                return_code=int(completed.returncode),
                timed_out=False,
                assignment_name=None if assignment_name is None else str(assignment_name),
                diagnostics=diagnostics,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            stdout_path.write_text(str(stdout), encoding="utf-8")
            stderr_path.write_text(str(stderr), encoding="utf-8")
            diagnostics["timeout_seconds"] = self.policy.timeout_seconds
            result = NgspiceCaseResult(
                case_name=case_name,
                status=NgspiceCaseStatus.TIMED_OUT,
                case_directory=str(case_dir),
                deck_path=str(deck_path),
                log_path=str(log_path),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                command=tuple(command),
                return_code=None,
                timed_out=True,
                assignment_name=None if assignment_name is None else str(assignment_name),
                diagnostics=diagnostics,
            )
        except OSError as exc:
            raise NgspiceExecutionError(
                f"failed to execute ngspice for {case_name}: {exc}"
            ) from exc

        self._write_json(case_dir / "result.json", result.to_dict())
        return result

    def _load_template(self, case: Any, manifest: Any) -> tuple[str, str]:
        inline = _read_attr(
            case, "template_text", "deck_template_text", default=None
        )
        if inline is None:
            template = _read_attr(manifest, "template", default=None)
            inline = _read_attr(
                template, "template_text", "text", "deck_template_text", default=None
            )
        if inline is not None:
            return str(inline), "<inline>"

        source = _read_attr(
            case,
            "template_source",
            "source",
            "deck_template",
            default=None,
        )
        if source is None:
            template = _read_attr(manifest, "template", default=None)
            source = _read_attr(
                template,
                "source",
                "template_source",
                "deck_template",
                default=None,
            )
        if source is None:
            raise NgspiceInputError("no SPICE template source was provided")

        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise NgspiceInputError(f"SPICE template does not exist: {path}")
        return path.read_text(encoding="utf-8"), str(path)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

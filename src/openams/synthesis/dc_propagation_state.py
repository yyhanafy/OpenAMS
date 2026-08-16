"""Generic ordered DC propagation runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class PropagationStateError(ValueError):
    """Raised when propagation state becomes invalid."""


@dataclass(frozen=True)
class Interval:
    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if self.minimum > self.maximum:
            raise PropagationStateError(
                f"invalid interval: {self.minimum} > {self.maximum}"
            )

    @property
    def is_exact(self) -> bool:
        return self.minimum == self.maximum

    def intersect(self, other: "Interval") -> "Interval":
        minimum = max(self.minimum, other.minimum)
        maximum = min(self.maximum, other.maximum)
        if minimum > maximum:
            raise PropagationStateError(
                f"empty interval intersection: [{self.minimum}, {self.maximum}] "
                f"with [{other.minimum}, {other.maximum}]"
            )
        return Interval(minimum, maximum)

    def to_dict(self) -> dict[str, float]:
        return {
            "minimum": float(self.minimum),
            "maximum": float(self.maximum),
        }


@dataclass
class PropagationState:
    """State for one independent design point."""

    independent_values: dict[str, float]
    scalars: dict[str, float] = field(default_factory=dict)
    intervals: dict[str, Interval] = field(default_factory=dict)
    candidate_sets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    operation_trace: list[dict[str, Any]] = field(default_factory=list)
    status: str = "PASS"
    failure_operation: str | None = None
    failure_reason: str | None = None
    last_completed_operation: str | None = None

    def __post_init__(self) -> None:
        self.scalars.update(
            {
                str(name): float(value)
                for name, value in self.independent_values.items()
            }
        )

    def set_scalar(self, name: str, value: float) -> None:
        self.scalars[str(name)] = float(value)

    def set_interval(self, name: str, interval: Interval) -> None:
        self.intervals[str(name)] = interval

    def intersect_interval(self, name: str, interval: Interval) -> None:
        if name in self.intervals:
            self.intervals[name] = self.intervals[name].intersect(interval)
        else:
            self.intervals[name] = interval

    def set_candidate_set(
        self,
        name: str,
        candidates: list[dict[str, Any]],
    ) -> None:
        self.candidate_sets[str(name)] = list(candidates)

    def fail(self, operation_id: str, reason: str) -> None:
        self.status = "FAIL"
        self.failure_operation = str(operation_id)
        self.failure_reason = str(reason)

    def record_operation(
        self,
        *,
        operation_id: str,
        operation_type: str,
        status: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        item: dict[str, Any] = {
            "id": str(operation_id),
            "type": str(operation_type),
            "status": str(status),
        }
        if details:
            item["details"] = dict(details)
        self.operation_trace.append(item)
        if status == "PASS":
            self.last_completed_operation = str(operation_id)

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            **self.independent_values,
            "status": self.status,
            "failure_operation": self.failure_operation,
            "failure_reason": self.failure_reason,
            "last_completed_operation": self.last_completed_operation,
        }

        for name, value in self.scalars.items():
            record.setdefault(name, value)

        for name, interval in self.intervals.items():
            base = name[:-2] if name.endswith("_v") else name
            record[f"{base}_min_v"] = interval.minimum
            record[f"{base}_max_v"] = interval.maximum

        for name, candidates in self.candidate_sets.items():
            record[f"{name[:-11] if name.endswith('_candidates') else name}_candidate_count"] = len(
                candidates
            )

        return record

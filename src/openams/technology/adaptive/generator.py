"""Generate explicit local tables by directly evaluating a continuous model."""
from __future__ import annotations

from itertools import islice, product
from math import exp, isfinite, log
from typing import Iterable, Iterator, Protocol, Sequence

from .errors import ModelEvaluationError, PointBudgetExceededError
from .model import (
    AdaptiveTable,
    AxisDomain,
    AxisSpacing,
    GeneratedPoint,
    GenerationPolicy,
    ModelEvaluation,
    SamplingDomain,
)


class ContinuousTechnologyModel(Protocol):
    """Minimal backend contract required by adaptive generation."""

    @property
    def identity(self) -> str: ...

    def evaluate_many(
        self, coordinates: Sequence[dict[str, float]]
    ) -> Sequence[ModelEvaluation]: ...


def axis_values(axis: AxisDomain) -> tuple[float, ...]:
    if axis.count == 1:
        return (float(axis.minimum),)
    if axis.spacing is AxisSpacing.LINEAR:
        step = (axis.maximum - axis.minimum) / (axis.count - 1)
        return tuple(axis.minimum + index * step for index in range(axis.count))
    lo, hi = log(axis.minimum), log(axis.maximum)
    step = (hi - lo) / (axis.count - 1)
    return tuple(exp(lo + index * step) for index in range(axis.count))


def coordinate_grid(domain: SamplingDomain) -> Iterator[dict[str, float]]:
    names = tuple(axis.name for axis in domain.axes)
    values = tuple(axis_values(axis) for axis in domain.axes)
    for coordinates in product(*values):
        yield dict(zip(names, coordinates, strict=True))


def _batches(items: Iterable[dict[str, float]], size: int) -> Iterator[list[dict[str, float]]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _finite(evaluation: ModelEvaluation) -> bool:
    return all(isfinite(value) for value in evaluation.coordinates.values()) and all(
        isfinite(value) for value in evaluation.quantities.values()
    )


class AdaptiveTableGenerator:
    """Direct model evaluator producing deterministic, finite local tables."""

    def __init__(
        self,
        model: ContinuousTechnologyModel,
        policy: GenerationPolicy | None = None,
    ) -> None:
        self._model = model
        self._policy = policy or GenerationPolicy()

    def generate(
        self,
        domain: SamplingDomain,
        *,
        generation_level: int = 0,
    ) -> AdaptiveTable:
        if domain.point_count > self._policy.max_points:
            raise PointBudgetExceededError(
                f"requested {domain.point_count} points exceeds max_points="
                f"{self._policy.max_points}"
            )

        points: list[GeneratedPoint] = []
        evaluated = 0
        rejected_non_finite = 0
        rejected_region = 0

        for batch in _batches(coordinate_grid(domain), self._policy.batch_size):
            try:
                results = tuple(self._model.evaluate_many(batch))
            except Exception as exc:  # model boundary
                raise ModelEvaluationError(f"continuous model evaluation failed: {exc}") from exc
            if len(results) != len(batch):
                raise ModelEvaluationError(
                    "continuous model returned a different number of results than requested"
                )
            for requested, result in zip(batch, results, strict=True):
                evaluated += 1
                if set(result.coordinates) != set(requested):
                    raise ModelEvaluationError(
                        "model result coordinate names do not match the sampling domain"
                    )
                if self._policy.reject_non_finite and not _finite(result):
                    rejected_non_finite += 1
                    continue
                if self._policy.require_saturation and result.saturated is not True:
                    rejected_region += 1
                    continue
                points.append(
                    GeneratedPoint(
                        coordinates=result.coordinates,
                        quantities=result.quantities,
                        region=result.region,
                        saturated=result.saturated,
                        generation_level=generation_level,
                        source=self._model.identity,
                        diagnostics=result.diagnostics,
                    )
                )

        return AdaptiveTable(
            points=tuple(points),
            domain=domain,
            model_identity=self._model.identity,
            generation_level=generation_level,
            metadata={
                "requested_point_count": domain.point_count,
                "evaluated_point_count": evaluated,
                "retained_point_count": len(points),
                "rejected_non_finite_count": rejected_non_finite,
                "rejected_region_count": rejected_region,
                "direct_model_evaluation": True,
                "interpolation_used": False,
            },
        )

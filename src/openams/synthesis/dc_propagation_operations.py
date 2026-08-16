"""Generic provider-independent DC propagation operation handlers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from openams.synthesis.dc_propagation_expressions import (
    ExpressionError,
    evaluate_expression,
)
from openams.synthesis.dc_propagation_state import (
    Interval,
    PropagationState,
    PropagationStateError,
)


class OperationExecutionError(ValueError):
    """Raised when a generic propagation operation cannot execute."""


def _operation_id(operation: Mapping[str, Any]) -> str:
    return str(operation.get("id", ""))


def _operation_type(operation: Mapping[str, Any]) -> str:
    return str(operation.get("type", ""))


def _fail(
    state: PropagationState,
    operation: Mapping[str, Any],
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    operation_id = _operation_id(operation)
    operation_type = _operation_type(operation)
    failure_reason = str(
        reason
        or operation.get("failure_reason")
        or "OPERATION_FAILED"
    )
    state.fail(operation_id, failure_reason)
    state.record_operation(
        operation_id=operation_id,
        operation_type=operation_type,
        status="FAIL",
        details=details,
    )


def _pass(
    state: PropagationState,
    operation: Mapping[str, Any],
    details: Mapping[str, Any] | None = None,
) -> None:
    state.record_operation(
        operation_id=_operation_id(operation),
        operation_type=_operation_type(operation),
        status="PASS",
        details=details,
    )


def execute_map_candidates(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    source_set = str(operation["source_set"])
    output_set = str(operation["output_set"])
    assignments = operation.get("assignments", {}) or {}

    if source_set not in state.candidate_sets:
        _fail(
            state,
            operation,
            "MISSING_SOURCE_CANDIDATE_SET",
            {"source_set": source_set},
        )
        return

    output: list[dict[str, Any]] = []

    try:
        for source_candidate in state.candidate_sets[source_set]:
            candidate = deepcopy(source_candidate)

            for field, definition in assignments.items():
                if not isinstance(definition, Mapping):
                    raise OperationExecutionError(
                        f"assignment {field!r} must be a mapping"
                    )

                expression = str(definition["expression"])
                candidate[str(field)] = evaluate_expression(
                    expression,
                    scalars=state.scalars,
                    intervals=state.intervals,
                    candidate=candidate,
                )

            output.append(candidate)
    except (ExpressionError, KeyError, OperationExecutionError) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "CANDIDATE_MAPPING_FAILED")),
            {"error": str(exc)},
        )
        return

    state.set_candidate_set(output_set, output)

    if not output and not bool(operation.get("allow_empty", False)):
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "EMPTY_MAPPED_CANDIDATE_SET")),
            {"output_set": output_set},
        )
        return

    _pass(
        state,
        operation,
        {
            "source_set": source_set,
            "output_set": output_set,
            "input_count": len(state.candidate_sets[source_set]),
            "output_count": len(output),
        },
    )


def execute_filter_candidates(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    source_set = str(operation["source_set"])
    output_set = str(operation["output_set"])
    conditions = operation.get("conditions", []) or []

    if source_set not in state.candidate_sets:
        _fail(
            state,
            operation,
            "MISSING_SOURCE_CANDIDATE_SET",
            {"source_set": source_set},
        )
        return

    output: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}

    try:
        for candidate in state.candidate_sets[source_set]:
            accepted = True

            for condition in conditions:
                if not isinstance(condition, Mapping):
                    raise OperationExecutionError(
                        "filter condition must be a mapping"
                    )

                expression = str(condition["expression"])
                passed = bool(
                    evaluate_expression(
                        expression,
                        scalars=state.scalars,
                        intervals=state.intervals,
                        candidate=candidate,
                    )
                )

                if not passed:
                    accepted = False
                    reason = str(
                        condition.get(
                            "failure_reason",
                            operation.get(
                                "failure_reason",
                                "FILTER_CONDITION_FAILED",
                            ),
                        )
                    )
                    rejection_counts[reason] = (
                        rejection_counts.get(reason, 0) + 1
                    )
                    break

            if accepted:
                output.append(deepcopy(candidate))
    except (ExpressionError, KeyError, OperationExecutionError) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "CANDIDATE_FILTER_FAILED")),
            {"error": str(exc)},
        )
        return

    state.set_candidate_set(output_set, output)

    if not output and not bool(operation.get("allow_empty", False)):
        reason = (
            max(
                rejection_counts,
                key=rejection_counts.get,
            )
            if rejection_counts
            else str(
                operation.get(
                    "failure_reason",
                    "EMPTY_FILTERED_CANDIDATE_SET",
                )
            )
        )
        _fail(
            state,
            operation,
            reason,
            {
                "source_set": source_set,
                "output_set": output_set,
                "input_count": len(state.candidate_sets[source_set]),
                "rejection_counts": rejection_counts,
            },
        )
        return

    _pass(
        state,
        operation,
        {
            "source_set": source_set,
            "output_set": output_set,
            "input_count": len(state.candidate_sets[source_set]),
            "output_count": len(output),
            "rejection_counts": rejection_counts,
        },
    )


def execute_reduce_interval(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    source_set = str(operation["source_set"])
    target = str(operation["target"])

    if source_set not in state.candidate_sets:
        _fail(
            state,
            operation,
            "MISSING_SOURCE_CANDIDATE_SET",
            {"source_set": source_set},
        )
        return

    candidates = state.candidate_sets[source_set]

    if not candidates:
        if bool(operation.get("allow_empty", False)):
            _pass(
                state,
                operation,
                {
                    "source_set": source_set,
                    "target": target,
                    "source_count": 0,
                },
            )
            return

        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "EMPTY_REDUCTION_SOURCE")),
            {"source_set": source_set},
        )
        return

    minimum_expression = operation.get("minimum_expression")
    maximum_expression = operation.get("maximum_expression")
    common_expression = operation.get("expression")

    if minimum_expression is None:
        minimum_expression = common_expression
    if maximum_expression is None:
        maximum_expression = common_expression

    if minimum_expression is None or maximum_expression is None:
        _fail(
            state,
            operation,
            "MISSING_REDUCTION_EXPRESSION",
            {"target": target},
        )
        return

    try:
        minimum_values = [
            float(
                evaluate_expression(
                    str(minimum_expression),
                    scalars=state.scalars,
                    intervals=state.intervals,
                    candidate=candidate,
                )
            )
            for candidate in candidates
        ]
        maximum_values = [
            float(
                evaluate_expression(
                    str(maximum_expression),
                    scalars=state.scalars,
                    intervals=state.intervals,
                    candidate=candidate,
                )
            )
            for candidate in candidates
        ]

        interval = Interval(
            min(minimum_values),
            max(maximum_values),
        )
        state.set_interval(target, interval)
    except (
        ExpressionError,
        KeyError,
        TypeError,
        ValueError,
        PropagationStateError,
    ) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "INTERVAL_REDUCTION_FAILED")),
            {"error": str(exc), "target": target},
        )
        return

    _pass(
        state,
        operation,
        {
            "source_set": source_set,
            "target": target,
            "source_count": len(candidates),
            "minimum": interval.minimum,
            "maximum": interval.maximum,
        },
    )


def execute_interval_alias(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    source = str(operation["source"])
    target = str(operation["target"])
    mode = str(operation.get("mode", "replace"))

    if source not in state.intervals:
        _fail(
            state,
            operation,
            "MISSING_SOURCE_INTERVAL",
            {"source": source},
        )
        return

    source_interval = state.intervals[source]

    try:
        if mode == "replace":
            state.set_interval(target, source_interval)
        elif mode == "intersect":
            state.intersect_interval(target, source_interval)
        else:
            raise OperationExecutionError(
                f"unsupported interval alias mode {mode!r}"
            )
    except (
        PropagationStateError,
        OperationExecutionError,
    ) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "INTERVAL_ALIAS_FAILED")),
            {"error": str(exc), "source": source, "target": target},
        )
        return

    target_interval = state.intervals[target]
    _pass(
        state,
        operation,
        {
            "source": source,
            "target": target,
            "mode": mode,
            "minimum": target_interval.minimum,
            "maximum": target_interval.maximum,
        },
    )


def execute_constraint(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    expression = str(operation["expression"])

    try:
        passed = bool(
            evaluate_expression(
                expression,
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )
    except ExpressionError as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "CONSTRAINT_EVALUATION_FAILED")),
            {"error": str(exc), "expression": expression},
        )
        return

    if not passed:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "CONSTRAINT_FAILED")),
            {"expression": expression},
        )
        return

    _pass(
        state,
        operation,
        {"expression": expression},
    )


PROVIDER_INDEPENDENT_HANDLERS = {
    "map_candidates": execute_map_candidates,
    "filter_candidates": execute_filter_candidates,
    "reduce_interval": execute_reduce_interval,
    "interval_alias": execute_interval_alias,
    "constraint": execute_constraint,
}


def execute_provider_independent_operation(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    operation_type = _operation_type(operation)

    if operation_type not in PROVIDER_INDEPENDENT_HANDLERS:
        raise OperationExecutionError(
            f"no provider-independent handler for {operation_type!r}"
        )

    PROVIDER_INDEPENDENT_HANDLERS[operation_type](
        operation,
        state,
    )

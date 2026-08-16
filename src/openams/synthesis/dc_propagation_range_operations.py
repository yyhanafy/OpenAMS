"""Schema-v2 generic ordered DC range-propagation operations.

No candidate sets. No joins. Each technology lookup scans the provider's
characterized rows and directly reduces matching rows into output intervals.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

from openams.synthesis.technology_range_query import (
    NumericBounds,
    RangeQuery,
    get_or_build_range_index,
)
from openams.synthesis.dc_propagation_expressions import (
    ExpressionError,
    evaluate_expression,
)
from openams.synthesis.dc_propagation_state import (
    Interval,
    PropagationState,
    PropagationStateError,
)
from openams.synthesis.generic_complete_step5 import (
    _device_map,
    _minimum_nf,
    _polarity,
    _width_policy,
)


class RangeOperationError(ValueError):
    pass


def _fail(
    state: PropagationState,
    operation: Mapping[str, Any],
    reason: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    operation_id = str(operation["id"])
    operation_type = str(operation["type"])
    state.fail(operation_id, reason)
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
        operation_id=str(operation["id"]),
        operation_type=str(operation["type"]),
        status="PASS",
        details=details,
    )


def _row_namespace(row: Any) -> dict[str, float]:
    return {
        "width_um": float(row.width_um),
        "vgs_v": float(row.vgs_v),
        "vds_v": float(row.vds_v),
        "vbs_v": float(row.vbs_v),
        "vdsat_v": (
            float(row.vdsat_v)
            if row.vdsat_v is not None
            else float("nan")
        ),
        "id_a": float(row.id_a),
        "current_density_a_per_um": (
            float(row.id_a) / float(row.width_um)
        ),
    }


def _evaluate_with_row(
    expression: str,
    *,
    state: PropagationState,
    row: Any,
) -> Any:
    return evaluate_expression(
        expression,
        scalars=state.scalars,
        intervals=state.intervals,
        candidate=_row_namespace(row),
    )


def _row_expression(expression: str) -> str:
    # Reuse the existing safe evaluator's candidate namespace.
    return str(expression).replace("row.", "candidate.")


def _technology_tolerances(
    model: Mapping[str, Any],
) -> tuple[float, float, float]:
    raw = (
        model["project_inputs"]["design_rules"]
        .get("technology_intersection", {})
    )
    current_rel = float(
        raw.get(
            "current_relative_tolerance",
            raw.get("current_rel_tolerance", 0.10),
        )
    )
    current_abs = float(
        raw.get(
            "current_absolute_tolerance_a",
            raw.get("current_abs_tolerance_a", 1e-6),
        )
    )
    voltage_tol = float(
        raw.get(
            "node_voltage_tolerance_v",
            raw.get("voltage_tolerance_v", 0.025),
        )
    )
    return current_rel, current_abs, voltage_tol


# OPENAMS_GENERIC_INDEXED_RANGE_QUERY_V1
_SIMPLE_ROW_BOUND = re.compile(
    r"^\s*row\.(vgs_v|current_density_a_per_um|id_a)\s*(>=|>|<=|<)\s*(.+?)\s*$"
)


def _merge_lower(current: float | None, value: float) -> float:
    return value if current is None else max(current, value)


def _merge_upper(current: float | None, value: float) -> float:
    return value if current is None else min(current, value)


def _indexed_bounds_from_conditions(
    row_conditions: list[Mapping[str, Any]],
    *,
    state: PropagationState,
) -> dict[str, NumericBounds]:
    """Extract safe scalar bounds for indexed prefiltering.

    This recognizes only simple comparisons whose RHS is independent of the
    technology row.  Original conditions remain authoritative and are still
    evaluated later for every candidate row.
    """
    raw: dict[str, list[float | None]] = {
        "vgs_v": [None, None],
        "current_density_a_per_um": [None, None],
        "id_a": [None, None],
    }

    for condition in row_conditions:
        expression = str(condition.get("expression", ""))
        match = _SIMPLE_ROW_BOUND.fullmatch(expression)
        if match is None:
            continue
        field, operator, rhs = match.groups()
        if "row." in rhs or "candidate." in rhs:
            continue
        try:
            value = float(
                evaluate_expression(
                    rhs,
                    scalars=state.scalars,
                    intervals=state.intervals,
                )
            )
        except Exception:
            continue
        if not math.isfinite(value):
            continue
        if operator in {">=", ">"}:
            raw[field][0] = _merge_lower(raw[field][0], value)
        else:
            raw[field][1] = _merge_upper(raw[field][1], value)

    return {
        field: NumericBounds(values[0], values[1])
        for field, values in raw.items()
        if values[0] is not None or values[1] is not None
    }



# OPENAMS_FAST_SIMPLE_ROW_CONDITIONS_V1
_FAST_SIMPLE_ROW_CONDITION = re.compile(
    r"^\s*row\.(vgs_v|current_density_a_per_um|id_a)\s*(>=|>|<=|<)\s*(.+?)\s*$"
)


def _compile_fast_row_conditions(
    row_conditions: list[Mapping[str, Any]],
    *,
    state: PropagationState,
) -> tuple[list[tuple[str, str, float]], list[Mapping[str, Any]]]:
    fast: list[tuple[str, str, float]] = []
    residual: list[Mapping[str, Any]] = []

    for condition in row_conditions:
        expression = str(condition.get("expression", ""))
        match = _FAST_SIMPLE_ROW_CONDITION.fullmatch(expression)
        if match is None:
            residual.append(condition)
            continue

        field, operator, rhs = match.groups()
        if "row." in rhs or "candidate." in rhs:
            residual.append(condition)
            continue

        try:
            value = float(
                evaluate_expression(
                    rhs,
                    scalars=state.scalars,
                    intervals=state.intervals,
                )
            )
        except Exception:
            residual.append(condition)
            continue

        if not math.isfinite(value):
            residual.append(condition)
            continue

        fast.append((field, operator, value))

    return fast, residual


def _fast_row_field(row: Any, field: str) -> float:
    if field == "vgs_v":
        return float(row.vgs_v)
    if field == "id_a":
        return float(row.id_a)
    if field == "current_density_a_per_um":
        return float(row.id_a) / float(row.width_um)
    raise RangeOperationError(f"unsupported fast row field {field!r}")


def _fast_compare(lhs: float, operator: str, rhs: float) -> bool:
    if operator == ">=":
        return lhs >= rhs
    if operator == ">":
        return lhs > rhs
    if operator == "<=":
        return lhs <= rhs
    if operator == "<":
        return lhs < rhs
    raise RangeOperationError(f"unsupported fast comparison {operator!r}")


def execute_technology_range_lookup(
    operation: Mapping[str, Any],
    state: PropagationState,
    *,
    model: Mapping[str, Any],
    provider: Any,
) -> None:
    """Scan characterized rows and reduce matching rows directly to ranges."""

    try:
        device_name = str(operation["device"]).upper()
        device = _device_map(model)[device_name]
        model_name = str(device["model"])
        polarity = _polarity(model_name)

        rules = (
            model["project_inputs"]["design_rules"]
            ["device_constraints"]["all_mos"]
        )
        length_um = float(rules["length_um"])

        current_spec = operation.get("current", {}) or {}
        current_mode = str(
            current_spec.get("mode", "constrained")
        )

        target_current: float | None = None

        if current_mode == "constrained":
            if "expression" not in current_spec:
                raise RangeOperationError(
                    "constrained current requires expression"
                )

            target_current = float(
                evaluate_expression(
                    str(current_spec["expression"]),
                    scalars=state.scalars,
                    intervals=state.intervals,
                )
            )

        elif current_mode == "unconstrained":
            target_current = None

        else:
            raise RangeOperationError(
                f"unsupported current mode {current_mode!r}"
            )

        width_spec = operation.get("width", {}) or {}
        width_mode = str(width_spec.get("mode", "variable"))

        fixed_width: float | None = None
        width_min: float | None = None
        width_max: float | None = None

        if width_mode in {"fixed", "fixed_scaled"}:
            fixed_width = float(
                evaluate_expression(
                    str(width_spec["expression"]),
                    scalars=state.scalars,
                    intervals=state.intervals,
                )
            )
        elif width_mode == "interval":
            width_min = float(
                evaluate_expression(
                    str(width_spec["minimum_expression"]),
                    scalars=state.scalars,
                    intervals=state.intervals,
                )
            )
            width_max = float(
                evaluate_expression(
                    str(width_spec["maximum_expression"]),
                    scalars=state.scalars,
                    intervals=state.intervals,
                )
            )
            if width_min > width_max:
                raise RangeOperationError(
                    f"empty width interval [{width_min}, {width_max}]"
                )
        elif width_mode not in {"variable", "characterized"}:
            raise RangeOperationError(
                f"unsupported width mode {width_mode!r}"
            )

        current_rel, current_abs, _voltage_tol = _technology_tolerances(model)
        allowed_current_error: float | None = None

        if target_current is not None:
            allowed_current_error = max(
                current_abs,
                current_rel * max(abs(target_current), 1e-30),
            )

        policy = _width_policy(model)
        require_saturation = bool(
            operation.get("require", {}).get("saturation", True)
        )
        row_conditions = operation.get("row_conditions", []) or []

        fast_row_conditions, residual_row_conditions = _compile_fast_row_conditions(
            row_conditions,
            state=state,
        )


        indexed_bounds = _indexed_bounds_from_conditions(
            row_conditions,
            state=state,
        )

        # A constrained current can itself provide an exact prefilter when the
        # characterized row current is the circuit current.  For fixed_scaled,
        # the same information becomes a density bound.
        if target_current is not None and allowed_current_error is not None:
            current_lo = max(0.0, target_current - allowed_current_error)
            current_hi = target_current + allowed_current_error
            if width_mode in {"fixed", "interval", "characterized"}:
                existing = indexed_bounds.get("id_a")
                lo = current_lo if existing is None or existing.minimum is None else max(current_lo, existing.minimum)
                hi = current_hi if existing is None or existing.maximum is None else min(current_hi, existing.maximum)
                indexed_bounds["id_a"] = NumericBounds(lo, hi)
            elif width_mode == "fixed_scaled" and fixed_width is not None and fixed_width > 0.0:
                density_lo = current_lo / fixed_width
                density_hi = current_hi / fixed_width
                existing = indexed_bounds.get("current_density_a_per_um")
                lo = density_lo if existing is None or existing.minimum is None else max(density_lo, existing.minimum)
                hi = density_hi if existing is None or existing.maximum is None else min(density_hi, existing.maximum)
                indexed_bounds["current_density_a_per_um"] = NumericBounds(lo, hi)


        # OPENAMS_INDEX_ONLY_UNCONSTRAINED_V1
        # Index only broad unconstrained-current searches. Current-conditioned
        # lookups retain the original exact scan and exact scaling semantics.
        current_spec = operation.get("current", {}) or {}
        current_mode = str(current_spec.get("mode", "target"))

        if current_mode == "unconstrained":
            range_index = get_or_build_range_index(provider)
            candidate_rows, query_stats = range_index.query(
                RangeQuery(
                    model=model_name,
                    polarity=polarity,
                    length_um=length_um,
                    vgs_v=indexed_bounds.get("vgs_v"),
                    current_density_a_per_um=indexed_bounds.get(
                        "current_density_a_per_um"
                    ),
                    id_a=indexed_bounds.get("id_a"),
                )
            )
            state.diagnostics[f"{operation['id']}_range_index"] = query_stats.index_name
            state.diagnostics[f"{operation['id']}_base_row_count"] = query_stats.base_row_count
            state.diagnostics[f"{operation['id']}_prefilter_row_count"] = query_stats.candidate_row_count
        else:
            candidate_rows = provider.rows
            state.diagnostics[f"{operation['id']}_range_index"] = "original_exact_scan"
            state.diagnostics[f"{operation['id']}_base_row_count"] = len(provider.rows)
            state.diagnostics[f"{operation['id']}_prefilter_row_count"] = len(provider.rows)

        matched: list[tuple[Any, float]] = []

        for row in candidate_rows:
            if row.model != model_name or row.polarity != polarity:
                continue
            if not math.isclose(
                float(row.length_um),
                length_um,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                continue
            if require_saturation and not bool(row.saturated):
                continue
            if row.vdsat_v is None:
                continue

            if width_mode == "fixed_scaled":
                assert fixed_width is not None
                if _minimum_nf(fixed_width, policy) is None:
                    continue
                predicted_current = (
                    float(row.id_a)
                    / float(row.width_um)
                    * fixed_width
                )
                realized_width = fixed_width

            elif width_mode == "fixed":
                assert fixed_width is not None
                if not math.isclose(
                    float(row.width_um),
                    fixed_width,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    continue
                if _minimum_nf(fixed_width, policy) is None:
                    continue
                predicted_current = float(row.id_a)
                realized_width = fixed_width

            elif width_mode == "interval":
                assert width_min is not None and width_max is not None
                realized_width = float(row.width_um)
                if realized_width < width_min or realized_width > width_max:
                    continue
                predicted_current = float(row.id_a)

            elif width_mode == "characterized":
                realized_width = float(row.width_um)
                if _minimum_nf(realized_width, policy) is None:
                    continue
                predicted_current = float(row.id_a)

            else:  # variable
                if target_current is None:
                    raise RangeOperationError(
                        "variable width requires constrained current"
                    )
                density = float(row.id_a) / float(row.width_um)
                if density <= 0.0:
                    continue
                realized_width = target_current / density
                if _minimum_nf(realized_width, policy) is None:
                    continue
                predicted_current = density * realized_width

            if target_current is not None:
                assert allowed_current_error is not None
                if (
                    abs(predicted_current - target_current)
                    > allowed_current_error
                ):
                    continue

            row_ok = True

            for field, operator, rhs in fast_row_conditions:
                if not _fast_compare(
                    _fast_row_field(row, field),
                    operator,
                    rhs,
                ):
                    row_ok = False
                    break

            if row_ok:
                for condition in residual_row_conditions:
                    expression = _row_expression(
                        str(condition["expression"])
                    )
                    if not bool(
                        _evaluate_with_row(
                            expression,
                            state=state,
                            row=row,
                        )
                    ):
                        row_ok = False
                        break

            if row_ok:
                matched.append((row, realized_width))

        if not matched:
            _fail(
                state,
                operation,
                str(
                    operation.get(
                        "failure_reason",
                        "NO_TECHNOLOGY_RANGE_REALIZATION",
                    )
                ),
                {
                    "device": device_name,
                    "target_current_a": target_current,
                    "current_mode": current_mode,
                    "width_mode": width_mode,
                },
            )
            return

        outputs = operation.get("outputs", {}) or {}
        for output_name, definition in outputs.items():
            source = str(definition["source"])
            if definition.get("reduction") != "range":
                raise RangeOperationError(
                    f"{output_name}: only reduction='range' is supported"
                )

            if source == "row.width_um":
                values = [float(width) for _row, width in matched]
            else:
                field = source.removeprefix("row.")
                values = []
                for row, _width in matched:
                    namespace = _row_namespace(row)
                    if field not in namespace:
                        raise RangeOperationError(
                            f"unsupported row field {field!r}"
                        )
                    value = float(namespace[field])
                    if math.isfinite(value):
                        values.append(value)

            if not values:
                raise RangeOperationError(
                    f"{output_name}: no finite values"
                )

            state.set_interval(
                str(output_name),
                Interval(min(values), max(values)),
            )

        # OPENAMS_COMPACT_WITNESS_REFS_V1
        # Retain only references to provider-owned ForwardRow objects.
        # Tuple layout: (technology_row_index, realized_width_um).
        witness_refs = [
            (int(row.index), float(realized_width))
            for row, realized_width in matched
        ]
        state.set_candidate_set(
            "__witness_lookup__" + str(operation["id"]),
            witness_refs,
        )

        state.diagnostics[f"{operation['id']}_row_count"] = len(matched)

        _pass(
            state,
            operation,
            {
                "device": device_name,
                "target_current_a": target_current,
                "current_mode": current_mode,
                "matching_row_count": len(matched),
            },
        )

    except (
        ExpressionError,
        KeyError,
        TypeError,
        ValueError,
        RangeOperationError,
    ) as exc:
        _fail(
            state,
            operation,
            str(
                operation.get(
                    "failure_reason",
                    "TECHNOLOGY_RANGE_LOOKUP_FAILED",
                )
            ),
            {"error": str(exc)},
        )


def execute_interval_equation(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    try:
        minimum = float(
            evaluate_expression(
                str(operation["minimum_expression"]),
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )
        maximum = float(
            evaluate_expression(
                str(operation["maximum_expression"]),
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )
        state.set_interval(
            str(operation["target"]),
            Interval(minimum, maximum),
        )
        _pass(
            state,
            operation,
            {"minimum": minimum, "maximum": maximum},
        )
    except (ExpressionError, KeyError, ValueError, PropagationStateError) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "INTERVAL_EQUATION_FAILED")),
            {"error": str(exc)},
        )


def execute_interval_intersection(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    target = str(operation["target"])
    initialize_if_missing = bool(
        operation.get("initialize_if_missing", False)
    )

    try:
        minimum = float(
            evaluate_expression(
                str(operation["minimum_expression"]),
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )
        maximum = float(
            evaluate_expression(
                str(operation["maximum_expression"]),
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )
        proposed = Interval(minimum, maximum)

        if target not in state.intervals:
            if not initialize_if_missing:
                _fail(
                    state,
                    operation,
                    "MISSING_TARGET_INTERVAL",
                    {"target": target},
                )
                return

            state.set_interval(target, proposed)
        else:
            state.intersect_interval(
                target,
                proposed,
            )

        result = state.intervals[target]
        _pass(
            state,
            operation,
            {
                "target": target,
                "minimum": result.minimum,
                "maximum": result.maximum,
            },
        )
    except (ExpressionError, KeyError, ValueError, PropagationStateError) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "EMPTY_INTERVAL_INTERSECTION")),
            {"error": str(exc), "target": target},
        )


def execute_lower_bound(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    target = str(operation["target"])
    try:
        bound = float(
            evaluate_expression(
                str(operation["expression"]),
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )
        if target in state.intervals:
            current = state.intervals[target]
            state.set_interval(
                target,
                Interval(max(current.minimum, bound), current.maximum),
            )
        else:
            state.set_interval(
                target,
                Interval(bound, float("inf")),
            )
        _pass(state, operation, {"target": target, "bound": bound})
    except (ExpressionError, ValueError, PropagationStateError) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "LOWER_BOUND_FAILED")),
            {"error": str(exc), "target": target},
        )


def execute_upper_bound(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    target = str(operation["target"])
    try:
        bound = float(
            evaluate_expression(
                str(operation["expression"]),
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )
        if target in state.intervals:
            current = state.intervals[target]
            state.set_interval(
                target,
                Interval(current.minimum, min(current.maximum, bound)),
            )
        else:
            state.set_interval(
                target,
                Interval(float("-inf"), bound),
            )
        _pass(state, operation, {"target": target, "bound": bound})
    except (ExpressionError, ValueError, PropagationStateError) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "UPPER_BOUND_FAILED")),
            {"error": str(exc), "target": target},
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

    try:
        if mode == "replace":
            state.set_interval(target, state.intervals[source])
        elif mode == "intersect":
            state.intersect_interval(target, state.intervals[source])
        else:
            raise RangeOperationError(
                f"unsupported alias mode {mode!r}"
            )
        _pass(state, operation, {"source": source, "target": target, "mode": mode})
    except (PropagationStateError, RangeOperationError) as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "INTERVAL_ALIAS_FAILED")),
            {"error": str(exc)},
        )


def execute_constraint(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    try:
        passed = bool(
            evaluate_expression(
                str(operation["expression"]),
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )
        if not passed:
            _fail(
                state,
                operation,
                str(operation.get("failure_reason", "CONSTRAINT_FAILED")),
            )
            return
        _pass(state, operation)
    except ExpressionError as exc:
        _fail(
            state,
            operation,
            str(operation.get("failure_reason", "CONSTRAINT_EVALUATION_FAILED")),
            {"error": str(exc)},
        )


RANGE_OPERATION_HANDLERS = {
    "interval_equation": execute_interval_equation,
    "interval_intersection": execute_interval_intersection,
    "lower_bound": execute_lower_bound,
    "upper_bound": execute_upper_bound,
    "interval_alias": execute_interval_alias,
    "constraint": execute_constraint,
}


def execute_range_operation(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    operation_type = str(operation["type"])
    if operation_type not in RANGE_OPERATION_HANDLERS:
        raise RangeOperationError(
            f"no range-operation handler for {operation_type!r}"
        )
    RANGE_OPERATION_HANDLERS[operation_type](operation, state)

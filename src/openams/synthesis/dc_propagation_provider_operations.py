"""Generic provider-aware DC propagation operation handlers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from openams.synthesis.dc_propagation_expressions import (
    ExpressionError,
    evaluate_expression,
)
from openams.synthesis.dc_propagation_operations import (
    OperationExecutionError,
    _fail,
    _pass,
)
from openams.synthesis.dc_propagation_state import PropagationState
from openams.synthesis.generic_complete_step5 import (
    DeviceRealization,
    DeviceRequest,
    _device_map,
    _minimum_nf,
    _polarity,
    _width_policy,
)


def _evaluate_optional_expression(
    definition: Any,
    *,
    state: PropagationState,
    candidate: Mapping[str, Any] | None = None,
) -> float | None:
    if definition is None:
        return None
    if not isinstance(definition, Mapping):
        raise OperationExecutionError(
            "expression definition must be a mapping"
        )
    if "expression" not in definition:
        return None
    return float(
        evaluate_expression(
            str(definition["expression"]),
            scalars=state.scalars,
            intervals=state.intervals,
            candidate=candidate,
        )
    )


def _realization_to_candidate(
    realization: DeviceRealization,
    produces: Mapping[str, Any],
) -> dict[str, Any]:
    source = {
        "width_um": realization.width_um,
        "nf": realization.nf,
        "finger_width_um": realization.finger_width_um,
        "predicted_current_a": realization.predicted_current_a,
        "vgs_v": realization.vgs_v,
        "vds_v": realization.vds_v,
        "vbs_v": realization.vbs_v,
        "vdsat_v": realization.vdsat_v,
        "saturated": realization.saturated,
        "provenance": dict(realization.provenance),
    }

    candidate: dict[str, Any] = {}

    for source_name, output_name in produces.items():
        if source_name not in source:
            raise OperationExecutionError(
                f"unsupported produced realization field {source_name!r}"
            )
        candidate[str(output_name)] = source[source_name]

    candidate.setdefault(
        "technology_provenance",
        dict(realization.provenance),
    )
    return candidate


def _scaled_fixed_width_candidates(
    provider: Any,
    request: DeviceRequest,
    *,
    model: Mapping[str, Any],
    current_relative_tolerance: float,
    current_absolute_tolerance_a: float,
    voltage_tolerance_v: float,
    limit: int,
) -> list[DeviceRealization]:
    if request.fixed_width_um is None:
        raise OperationExecutionError(
            "fixed_scaled width mode requires a fixed width"
        )

    if not hasattr(provider, "rows"):
        raise OperationExecutionError(
            "fixed_scaled lookup requires a provider exposing characterized rows"
        )

    allowed_error = max(
        current_absolute_tolerance_a,
        current_relative_tolerance
        * max(abs(request.target_current_a), 1e-30),
    )

    policy = _width_policy(model)
    nf = _minimum_nf(request.fixed_width_um, policy)
    if nf is None:
        return []

    grouped: dict[tuple[float, float], list[tuple[Any, float]]] = {}

    for row in provider.rows:
        if row.model != request.model:
            continue
        if row.polarity != request.polarity:
            continue
        if abs(row.length_um - request.length_um) > 1e-12:
            continue
        if row.width_um <= 0.0:
            continue

        predicted = (
            float(row.id_a)
            / float(row.width_um)
            * float(request.fixed_width_um)
        )

        if abs(predicted - request.target_current_a) > allowed_error:
            continue

        if (
            request.known_vgs_v is not None
            and abs(float(row.vgs_v) - request.known_vgs_v)
            > voltage_tolerance_v
        ):
            continue

        if (
            request.known_vbs_v is not None
            and abs(float(row.vbs_v) - request.known_vbs_v)
            > voltage_tolerance_v
        ):
            continue

        grouped.setdefault(
            (
                round(float(row.vgs_v), 12),
                round(float(row.vbs_v), 12),
            ),
            [],
        ).append((row, predicted))

    result: list[tuple[tuple[float, float, float], DeviceRealization]] = []

    for support in grouped.values():
        best_row, best_current = min(
            support,
            key=lambda item: abs(
                item[1] - request.target_current_a
            ),
        )

        vdsat_values = [
            float(row.vdsat_v)
            for row, _predicted in support
            if row.vdsat_v is not None
        ]
        if not vdsat_values:
            continue

        minimum_vds = min(float(row.vds_v) for row, _ in support)
        maximum_vds = max(float(row.vds_v) for row, _ in support)
        maximum_vdsat = max(vdsat_values)
        current_error = abs(best_current - request.target_current_a)

        realization = DeviceRealization(
            width_um=float(request.fixed_width_um),
            nf=nf,
            finger_width_um=float(request.fixed_width_um) / nf,
            predicted_current_a=float(best_current),
            vgs_v=float(best_row.vgs_v),
            vds_v=minimum_vds,
            vbs_v=float(best_row.vbs_v),
            vdsat_v=maximum_vdsat,
            saturated=True,
            provenance={
                "provider": "generic_fixed_scaled_density",
                "technology_source": str(getattr(provider, "path", "")),
                "scaling_model": "linear_current_density",
                "characterized_width_um": float(best_row.width_um),
                "requested_width_um": float(request.fixed_width_um),
                "minimum_saturated_vds_v": minimum_vds,
                "maximum_characterized_vds_v": maximum_vds,
                "maximum_vdsat_v": maximum_vdsat,
                "current_absolute_error_a": current_error,
                "current_relative_error": (
                    current_error
                    / max(abs(request.target_current_a), 1e-30)
                ),
            },
        )

        result.append(
            (
                (
                    current_error
                    / max(abs(request.target_current_a), 1e-30),
                    realization.vgs_v,
                    realization.vbs_v,
                ),
                realization,
            )
        )

    result.sort(key=lambda item: item[0])
    return [item[1] for item in result[:limit]]


def execute_technology_lookup(
    operation: Mapping[str, Any],
    state: PropagationState,
    *,
    model: Mapping[str, Any],
    provider: Any,
    current_relative_tolerance: float,
    current_absolute_tolerance_a: float,
    voltage_tolerance_v: float,
    max_candidates: int,
) -> None:
    request_spec = operation["request"]
    output_set = str(operation["output_set"])
    devices = [str(name) for name in request_spec["devices"]]
    representative = devices[0]

    try:
        target_current = float(
            evaluate_expression(
                str(request_spec["target_current"]["expression"]),
                scalars=state.scalars,
                intervals=state.intervals,
            )
        )

        width_spec = request_spec.get("width", {}) or {}
        width_mode = str(width_spec.get("mode", "variable"))

        fixed_width: float | None = None
        shared_candidates: Sequence[Mapping[str, Any]] = ({},)

        if width_mode in {"fixed", "fixed_scaled"}:
            fixed_width = float(
                evaluate_expression(
                    str(width_spec["expression"]),
                    scalars=state.scalars,
                    intervals=state.intervals,
                )
            )
        elif width_mode == "shared":
            source_set = str(width_spec["source_set"])
            source_field = str(width_spec["source_field"])
            if source_set not in state.candidate_sets:
                raise OperationExecutionError(
                    f"shared-width source set {source_set!r} is missing"
                )
            shared_candidates = state.candidate_sets[source_set]
            if not shared_candidates:
                raise OperationExecutionError(
                    f"shared-width source set {source_set!r} is empty"
                )
        elif width_mode != "variable":
            raise OperationExecutionError(
                f"unsupported width mode {width_mode!r}"
            )

        known = request_spec.get("known", {}) or {}
        device_map = _device_map(model)
        device = device_map[representative.upper()]
        all_mos = (
            model["project_inputs"]["design_rules"]
            ["device_constraints"]["all_mos"]
        )

        realizations: list[DeviceRealization] = []

        for shared_candidate in shared_candidates:
            request_width = fixed_width
            if width_mode == "shared":
                request_width = float(
                    shared_candidate[str(width_spec["source_field"])]
                )

            request = DeviceRequest(
                device=representative.upper(),
                model=str(device["model"]),
                polarity=_polarity(str(device["model"])),
                length_um=float(all_mos["length_um"]),
                target_current_a=target_current,
                fixed_width_um=request_width,
                known_vgs_v=_evaluate_optional_expression(
                    known.get("gate_voltage"),
                    state=state,
                    candidate=shared_candidate,
                ),
                known_vds_v=_evaluate_optional_expression(
                    known.get("drain_voltage"),
                    state=state,
                    candidate=shared_candidate,
                ),
                known_vbs_v=None,
                require_saturation=bool(
                    request_spec.get("require", {})
                    .get("saturation", True)
                ),
            )

            if width_mode == "fixed_scaled":
                found = _scaled_fixed_width_candidates(
                    provider,
                    request,
                    model=model,
                    current_relative_tolerance=current_relative_tolerance,
                    current_absolute_tolerance_a=current_absolute_tolerance_a,
                    voltage_tolerance_v=voltage_tolerance_v,
                    limit=max_candidates,
                )
            else:
                found = list(
                    provider.candidates(
                        request,
                        current_relative_tolerance=current_relative_tolerance,
                        current_absolute_tolerance_a=current_absolute_tolerance_a,
                        voltage_tolerance_v=voltage_tolerance_v,
                        width_policy=_width_policy(model),
                        limit=max_candidates,
                    )
                )

            realizations.extend(found)

        produces = request_spec.get("produces", {}) or {}
        candidates = [
            _realization_to_candidate(item, produces)
            for item in realizations
        ]

        state.set_candidate_set(output_set, candidates)

        if not candidates and not bool(operation.get("allow_empty", False)):
            _fail(
                state,
                operation,
                str(
                    operation.get(
                        "failure_reason",
                        "NO_TECHNOLOGY_REALIZATION",
                    )
                ),
                {
                    "output_set": output_set,
                    "devices": devices,
                    "target_current_a": target_current,
                    "width_mode": width_mode,
                },
            )
            return

        _pass(
            state,
            operation,
            {
                "output_set": output_set,
                "devices": devices,
                "target_current_a": target_current,
                "width_mode": width_mode,
                "candidate_count": len(candidates),
            },
        )
    except (
        ExpressionError,
        KeyError,
        TypeError,
        ValueError,
        OperationExecutionError,
    ) as exc:
        _fail(
            state,
            operation,
            str(
                operation.get(
                    "failure_reason",
                    "TECHNOLOGY_LOOKUP_FAILED",
                )
            ),
            {"error": str(exc)},
        )


def execute_join_candidates(
    operation: Mapping[str, Any],
    state: PropagationState,
) -> None:
    left_set = str(operation["left_set"])
    right_set = str(operation["right_set"])
    output_set = str(operation["output_set"])
    equality_keys = operation.get("equality_keys", []) or []
    conditions = operation.get("conditions", []) or []
    assignments = operation.get("assignments", {}) or {}

    if left_set not in state.candidate_sets:
        _fail(
            state,
            operation,
            "MISSING_LEFT_CANDIDATE_SET",
            {"left_set": left_set},
        )
        return

    if right_set not in state.candidate_sets:
        _fail(
            state,
            operation,
            "MISSING_RIGHT_CANDIDATE_SET",
            {"right_set": right_set},
        )
        return

    output: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}

    try:
        for left in state.candidate_sets[left_set]:
            for right in state.candidate_sets[right_set]:
                matched = True

                for key in equality_keys:
                    left_field = str(key["left"])
                    right_field = str(key["right"])
                    if left.get(left_field) != right.get(right_field):
                        matched = False
                        break

                if not matched:
                    continue

                candidate = {
                    **deepcopy(left),
                    **deepcopy(right),
                }

                for field, definition in assignments.items():
                    candidate[str(field)] = evaluate_expression(
                        str(definition["expression"]),
                        scalars=state.scalars,
                        intervals=state.intervals,
                        candidate=candidate,
                        left=left,
                        right=right,
                    )

                accepted = True
                for condition in conditions:
                    passed = bool(
                        evaluate_expression(
                            str(condition["expression"]),
                            scalars=state.scalars,
                            intervals=state.intervals,
                            candidate=candidate,
                            left=left,
                            right=right,
                        )
                    )
                    if not passed:
                        accepted = False
                        reason = str(
                            condition.get(
                                "failure_reason",
                                operation.get(
                                    "failure_reason",
                                    "JOIN_CONDITION_FAILED",
                                ),
                            )
                        )
                        rejection_counts[reason] = (
                            rejection_counts.get(reason, 0) + 1
                        )
                        break

                if accepted:
                    output.append(candidate)
    except (ExpressionError, KeyError, TypeError, ValueError) as exc:
        _fail(
            state,
            operation,
            str(
                operation.get(
                    "failure_reason",
                    "CANDIDATE_JOIN_FAILED",
                )
            ),
            {"error": str(exc)},
        )
        return

    state.set_candidate_set(output_set, output)

    if not output and not bool(operation.get("allow_empty", False)):
        reason = (
            max(rejection_counts, key=rejection_counts.get)
            if rejection_counts
            else str(
                operation.get(
                    "failure_reason",
                    "EMPTY_JOINED_CANDIDATE_SET",
                )
            )
        )
        _fail(
            state,
            operation,
            reason,
            {
                "left_set": left_set,
                "right_set": right_set,
                "output_set": output_set,
                "left_count": len(state.candidate_sets[left_set]),
                "right_count": len(state.candidate_sets[right_set]),
                "rejection_counts": rejection_counts,
            },
        )
        return

    _pass(
        state,
        operation,
        {
            "left_set": left_set,
            "right_set": right_set,
            "output_set": output_set,
            "left_count": len(state.candidate_sets[left_set]),
            "right_count": len(state.candidate_sets[right_set]),
            "output_count": len(output),
            "rejection_counts": rejection_counts,
        },
    )

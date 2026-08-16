"""Generic ordered DC propagation executor."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from openams.synthesis.dc_propagation_expressions import (
    ExpressionError,
    evaluate_expression,
)
from openams.synthesis.dc_propagation_operations import (
    PROVIDER_INDEPENDENT_HANDLERS,
    execute_provider_independent_operation,
)
from openams.synthesis.dc_propagation_provider_operations import (
    execute_join_candidates,
    execute_technology_lookup,
)
from openams.synthesis.dc_propagation_state import (
    Interval,
    PropagationState,
)
from openams.synthesis.inverse_feasible_provider import (
    InverseFeasibleDatasetProvider,
)


class ExecutorError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ExecutorError(f"{path}: root must be a mapping")
    return value


def _linspace(minimum: float, maximum: float, count: int) -> list[float]:
    if count <= 0:
        raise ExecutorError("sample count must be positive")
    if count == 1:
        return [0.5 * (minimum + maximum)]
    step = (maximum - minimum) / (count - 1)
    return [minimum + index * step for index in range(count)]


def _domain_values(
    independent_regions: Mapping[str, Any],
    variable_name: str,
    *,
    sample_overrides: Mapping[str, int],
    range_overrides: Mapping[str, tuple[float, float]],
) -> list[float]:
    domains = independent_regions.get("domains", {})
    if variable_name not in domains:
        raise ExecutorError(
            f"independent domain {variable_name!r} is missing"
        )

    domain = domains[variable_name]
    candidates = [
        float(value)
        for value in domain.get("candidate_values", []) or []
    ]
    if candidates:
        return candidates

    minimum = float(domain["technology_minimum"])
    maximum = float(domain["technology_maximum"])

    if variable_name in range_overrides:
        requested_minimum, requested_maximum = range_overrides[variable_name]
        minimum = max(minimum, requested_minimum)
        maximum = min(maximum, requested_maximum)

    if minimum > maximum:
        raise ExecutorError(
            f"empty range override for {variable_name!r}"
        )

    sample_count = sample_overrides.get(variable_name)
    if sample_count is None:
        embedded = domain.get("sample_count")
        if embedded is not None:
            sample_count = int(embedded)

    if sample_count is None:
        raise ExecutorError(
            f"continuous independent variable {variable_name!r} "
            "requires a sample count"
        )

    return _linspace(minimum, maximum, sample_count)


def _parse_name_int(items: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        name, separator, raw = item.partition("=")
        if not separator:
            raise ExecutorError(
                f"expected NAME=COUNT, got {item!r}"
            )
        result[name] = int(raw)
    return result


def _parse_name_range(
    items: list[str],
) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    for item in items:
        name, separator, raw = item.partition("=")
        if not separator:
            raise ExecutorError(
                f"expected NAME=MIN:MAX, got {item!r}"
            )
        raw_minimum, colon, raw_maximum = raw.partition(":")
        if not colon:
            raise ExecutorError(
                f"expected NAME=MIN:MAX, got {item!r}"
            )
        result[name] = (
            float(raw_minimum),
            float(raw_maximum),
        )
    return result


def _technology_tolerances(
    model: Mapping[str, Any],
) -> dict[str, float]:
    raw = (
        model["project_inputs"]["design_rules"]
        .get("technology_intersection", {})
    )
    return {
        "current_relative_tolerance": float(
            raw.get(
                "current_relative_tolerance",
                raw.get("current_rel_tolerance", 0.10),
            )
        ),
        "current_absolute_tolerance_a": float(
            raw.get(
                "current_absolute_tolerance_a",
                raw.get("current_abs_tolerance_a", 1e-6),
            )
        ),
        "voltage_tolerance_v": float(
            raw.get(
                "node_voltage_tolerance_v",
                raw.get("voltage_tolerance_v", 0.025),
            )
        ),
    }


def _resolve_source(
    source: str,
    model: Mapping[str, Any],
) -> float:
    parts = str(source).split(".")
    value: Any = model["project_inputs"]["design_rules"]

    if parts and parts[0] == "operating_conditions":
        value = value.get("operating_conditions", {})
        parts = parts[1:]

    for part in parts:
        if not isinstance(value, Mapping) or part not in value:
            raise ExecutorError(
                f"cannot resolve constant source {source!r}"
            )
        value = value[part]

    return float(value)


def _initialize_state(
    *,
    independent_values: Mapping[str, float],
    compiled_plan: Mapping[str, Any],
    model: Mapping[str, Any],
) -> PropagationState:
    state = PropagationState(
        independent_values={
            str(name): float(value)
            for name, value in independent_values.items()
        }
    )

    constants = compiled_plan.get("constants", {}) or {}

    pending = dict(constants)
    while pending:
        next_pending: dict[str, Any] = {}
        progress = False

        for name, definition in pending.items():
            if "source" in definition:
                value = _resolve_source(
                    str(definition["source"]),
                    model,
                )
                state.set_scalar(name, value)
                state.set_interval(name, Interval(value, value))
                progress = True
                continue

            if "expression" in definition:
                try:
                    value = float(
                        evaluate_expression(
                            str(definition["expression"]),
                            scalars=state.scalars,
                            intervals=state.intervals,
                        )
                    )
                except ExpressionError:
                    next_pending[name] = definition
                    continue

                state.set_scalar(name, value)
                state.set_interval(name, Interval(value, value))
                progress = True
                continue

            raise ExecutorError(
                f"constant {name!r} defines neither source nor expression"
            )

        if not progress:
            raise ExecutorError(
                "could not resolve constants: "
                + ", ".join(sorted(next_pending))
            )

        pending = next_pending

    tolerances = _technology_tolerances(model)
    state.set_scalar(
        "voltage_tolerance_v",
        tolerances["voltage_tolerance_v"],
    )
    state.set_scalar(
        "current_relative_tolerance",
        tolerances["current_relative_tolerance"],
    )
    state.set_scalar(
        "current_absolute_tolerance_a",
        tolerances["current_absolute_tolerance_a"],
    )

    return state


def execute_point(
    *,
    compiled_plan: Mapping[str, Any],
    model: Mapping[str, Any],
    provider: Any,
    independent_values: Mapping[str, float],
    max_candidates: int,
) -> PropagationState:
    state = _initialize_state(
        independent_values=independent_values,
        compiled_plan=compiled_plan,
        model=model,
    )
    tolerances = _technology_tolerances(model)

    for operation in compiled_plan.get("operations", []) or []:
        if state.status == "FAIL":
            break

        operation_type = str(operation["type"])

        if operation_type == "technology_lookup":
            execute_technology_lookup(
                operation,
                state,
                model=model,
                provider=provider,
                current_relative_tolerance=tolerances[
                    "current_relative_tolerance"
                ],
                current_absolute_tolerance_a=tolerances[
                    "current_absolute_tolerance_a"
                ],
                voltage_tolerance_v=tolerances[
                    "voltage_tolerance_v"
                ],
                max_candidates=max_candidates,
            )
        elif operation_type == "join_candidates":
            execute_join_candidates(operation, state)
        elif operation_type in PROVIDER_INDEPENDENT_HANDLERS:
            execute_provider_independent_operation(
                operation,
                state,
            )
        else:
            raise ExecutorError(
                f"no runtime handler for operation type "
                f"{operation_type!r}"
            )

    return state


def _requested_output_record(
    *,
    state: PropagationState,
    compiled_plan: Mapping[str, Any],
    point_index: int,
) -> dict[str, Any]:
    record = state.to_record()
    record["point_index"] = int(point_index)

    outputs = compiled_plan.get("outputs", {}) or {}

    for name in outputs.get("node_intervals", []) or []:
        base = name[:-2] if str(name).endswith("_v") else str(name)
        record.setdefault(f"{base}_min_v", None)
        record.setdefault(f"{base}_max_v", None)

    for name in outputs.get("scalar_ranges", []) or []:
        base = str(name)
        record.setdefault(f"{base}_min", None)
        record.setdefault(f"{base}_max", None)

        if name in state.intervals:
            interval = state.intervals[name]
            record[f"{base}_min"] = interval.minimum
            record[f"{base}_max"] = interval.maximum

    for set_name in outputs.get("candidate_counts", []) or []:
        base = (
            str(set_name)[:-11]
            if str(set_name).endswith("_candidates")
            else str(set_name)
        )
        record[f"{base}_candidate_count"] = len(
            state.candidate_sets.get(str(set_name), [])
        )

    record["operation_trace"] = list(state.operation_trace)
    return record


def run_design_space(
    *,
    compiled_plan_path: Path,
    compiled_model_path: Path,
    independent_regions_path: Path,
    technology_csv_path: Path,
    sample_overrides: Mapping[str, int],
    range_overrides: Mapping[str, tuple[float, float]],
    max_candidates: int,
) -> dict[str, Any]:
    plan = _load_json(compiled_plan_path)
    model = _load_json(compiled_model_path)
    independent_regions = _load_json(independent_regions_path)

    if plan.get("artifact") != "openams.compiled_dc_propagation_plan":
        raise ExecutorError(
            "compiled plan has the wrong artifact type"
        )

    variable_names = [
        str(name)
        for name in plan.get("independent_variables", []) or []
    ]

    values_by_name = {
        name: _domain_values(
            independent_regions,
            name,
            sample_overrides=sample_overrides,
            range_overrides=range_overrides,
        )
        for name in variable_names
    }

    combinations = itertools.product(
        *(values_by_name[name] for name in variable_names)
    )

    provider = InverseFeasibleDatasetProvider(
        technology_csv_path,
        saturation_margin_v=float(
            model["project_inputs"]["design_rules"]
            .get("technology_intersection", {})
            .get("saturation_margin_v", 0.0)
        ),
    )

    records: list[dict[str, Any]] = []

    for point_index, values in enumerate(combinations):
        independent_values = dict(zip(variable_names, values))
        state = execute_point(
            compiled_plan=plan,
            model=model,
            provider=provider,
            independent_values=independent_values,
            max_candidates=max_candidates,
        )
        records.append(
            _requested_output_record(
                state=state,
                compiled_plan=plan,
                point_index=point_index,
            )
        )

    status_counts = Counter(
        str(record["status"])
        for record in records
    )
    failure_counts = Counter(
        str(record["failure_operation"])
        for record in records
        if record["status"] == "FAIL"
    )

    return {
        "artifact": "openams.generic_ordered_dc_design_space",
        "schema_version": 1,
        "status": "PASS",
        "algorithm": "compiled_metadata_ordered_dc_propagation",
        "circuit_name": plan.get("circuit_name"),
        "compiled_plan": str(compiled_plan_path.resolve()),
        "compiled_model": str(compiled_model_path.resolve()),
        "independent_regions": str(independent_regions_path.resolve()),
        "technology_source": str(technology_csv_path.resolve()),
        "independent_variables": variable_names,
        "independent_values": values_by_name,
        "independent_point_count": len(records),
        "pass_count": status_counts.get("PASS", 0),
        "fail_count": status_counts.get("FAIL", 0),
        "failure_operation_counts": dict(
            sorted(failure_counts.items())
        ),
        "technology_provider_query_count": int(
            getattr(provider, "query_count", 0)
        ),
        "records": records,
    }


def write_outputs(
    artifact: Mapping[str, Any],
    *,
    json_path: Path,
    csv_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps(artifact, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    records = list(artifact.get("records", []) or [])
    if not records:
        raise ExecutorError("cannot write CSV without records")

    fields = sorted(
        {
            key
            for record in records
            for key in record
            if key != "operation_trace"
        },
        key=lambda key: (
            key not in {
                "point_index",
                *artifact.get("independent_variables", []),
                "status",
                "failure_operation",
                "failure_reason",
                "last_completed_operation",
            },
            key,
        ),
    )

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    key: value
                    for key, value in record.items()
                    if key != "operation_trace"
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compiled-plan",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--compiled-model",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--independent-regions",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--technology-csv",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--sample",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--range",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=2048,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    artifact = run_design_space(
        compiled_plan_path=args.compiled_plan,
        compiled_model_path=args.compiled_model,
        independent_regions_path=args.independent_regions,
        technology_csv_path=args.technology_csv,
        sample_overrides=_parse_name_int(args.sample),
        range_overrides=_parse_name_range(args.range),
        max_candidates=args.max_candidates,
    )

    write_outputs(
        artifact,
        json_path=args.output_json,
        csv_path=args.output_csv,
    )

    print("===== OPENAMS GENERIC ORDERED DC DESIGN SPACE =====")
    print(f"algorithm:          {artifact['algorithm']}")
    print(f"circuit:            {artifact['circuit_name']}")
    print(f"independent points: {artifact['independent_point_count']}")
    print(f"PASS:               {artifact['pass_count']}")
    print(f"FAIL:               {artifact['fail_count']}")
    print(f"JSON:               {args.output_json}")
    print(f"CSV:                {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generic schema-v2 ordered DC propagation executor.

Topology-neutral by construction:
- no hard-coded device names
- no hard-coded node names
- no hard-coded current equations
- no hard-coded operation order

All topology semantics come from the schema-v2 metadata plan.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import importlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from openams.synthesis.dc_propagation_expressions import (
    ExpressionError,
    evaluate_expression,
)
from openams.synthesis.dc_propagation_range_operations import (
    RANGE_OPERATION_HANDLERS,
    execute_range_operation,
    execute_technology_range_lookup,
)
from openams.synthesis.dc_propagation_state import (
    Interval,
    PropagationState,
)
from openams.synthesis.inverse_feasible_provider import (
    InverseFeasibleDatasetProvider,
)


class RangeExecutorError(ValueError):
    pass

def _load_witness_resolver(spec: str | None):
    if not spec:
        return None
    module_name, sep, function_name = str(spec).partition(":")
    if not sep:
        raise RangeExecutorError("witness resolver must be MODULE:FUNCTION")
    module = importlib.import_module(module_name)
    fn = getattr(module,function_name)
    if not callable(fn):
        raise RangeExecutorError(f"witness resolver {spec!r} is not callable")
    return fn

def _write_jsonl(path: Path, records: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record,sort_keys=True,default=str)+"\n")


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RangeExecutorError(f"{path}: root must be a mapping")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RangeExecutorError(f"{path}: root must be a mapping")
    return value


def _linspace(minimum: float, maximum: float, count: int) -> list[float]:
    if count <= 0:
        raise RangeExecutorError("sample count must be positive")
    if count == 1:
        return [0.5 * (minimum + maximum)]
    step = (maximum - minimum) / (count - 1)
    return [minimum + index * step for index in range(count)]


def _parse_name_int(items: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        name, separator, raw = item.partition("=")
        if not separator:
            raise RangeExecutorError(
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
            raise RangeExecutorError(
                f"expected NAME=MIN:MAX, got {item!r}"
            )
        raw_minimum, colon, raw_maximum = raw.partition(":")
        if not colon:
            raise RangeExecutorError(
                f"expected NAME=MIN:MAX, got {item!r}"
            )
        result[name] = (
            float(raw_minimum),
            float(raw_maximum),
        )
    return result


def _domain_values(
    independent_regions: Mapping[str, Any],
    variable_name: str,
    *,
    sample_overrides: Mapping[str, int],
    range_overrides: Mapping[str, tuple[float, float]],
) -> list[float]:
    domains = independent_regions.get("domains", {}) or {}

    if variable_name not in domains:
        raise RangeExecutorError(
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
        raise RangeExecutorError(
            f"empty range override for {variable_name!r}"
        )

    sample_count = sample_overrides.get(variable_name)
    if sample_count is None:
        embedded_count = domain.get("sample_count")
        if embedded_count is not None:
            sample_count = int(embedded_count)

    if sample_count is None:
        raise RangeExecutorError(
            f"continuous independent variable {variable_name!r} "
            "requires a sample count"
        )

    return _linspace(minimum, maximum, sample_count)


def _resolve_constant_source(
    source: str,
    model: Mapping[str, Any],
) -> float:
    parts = str(source).split(".")
    root = model["project_inputs"]["design_rules"]

    if parts and parts[0] == "operating_conditions":
        root = root.get("operating_conditions", {})
        parts = parts[1:]

    value: Any = root
    for part in parts:
        if not isinstance(value, Mapping) or part not in value:
            raise RangeExecutorError(
                f"cannot resolve constant source {source!r}"
            )
        value = value[part]

    return float(value)


def _initialize_state(
    *,
    independent_values: Mapping[str, float],
    plan: Mapping[str, Any],
    model: Mapping[str, Any],
) -> PropagationState:
    state = PropagationState(
        independent_values={
            str(name): float(value)
            for name, value in independent_values.items()
        }
    )

    constants = dict(plan.get("constants", {}) or {})
    pending = constants

    while pending:
        next_pending: dict[str, Any] = {}
        progress = False

        for name, definition in pending.items():
            if not isinstance(definition, Mapping):
                raise RangeExecutorError(
                    f"constant {name!r} definition must be a mapping"
                )

            if "source" in definition:
                value = _resolve_constant_source(
                    str(definition["source"]),
                    model,
                )
                state.set_scalar(str(name), value)
                state.set_interval(
                    str(name),
                    Interval(value, value),
                )
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
                    next_pending[str(name)] = definition
                    continue

                state.set_scalar(str(name), value)
                state.set_interval(
                    str(name),
                    Interval(value, value),
                )
                progress = True
                continue

            raise RangeExecutorError(
                f"constant {name!r} defines neither source nor expression"
            )

        if not progress:
            raise RangeExecutorError(
                "could not resolve constants: "
                + ", ".join(sorted(next_pending))
            )

        pending = next_pending

    technology = (
        model["project_inputs"]["design_rules"]
        .get("technology_intersection", {})
    )

    state.set_scalar(
        "voltage_tolerance_v",
        float(
            technology.get(
                "node_voltage_tolerance_v",
                technology.get("voltage_tolerance_v", 0.025),
            )
        ),
    )
    state.set_scalar(
        "current_relative_tolerance",
        float(
            technology.get(
                "current_relative_tolerance",
                technology.get("current_rel_tolerance", 0.10),
            )
        ),
    )
    state.set_scalar(
        "current_absolute_tolerance_a",
        float(
            technology.get(
                "current_absolute_tolerance_a",
                technology.get("current_abs_tolerance_a", 1e-6),
            )
        ),
    )

    return state


def _evaluate_derived_variables(
    *,
    state: PropagationState,
    plan: Mapping[str, Any],
) -> None:
    for item in plan.get("derived_variables", []) or []:
        name = str(item["id"])
        expression = str(item["expression"])

        try:
            value = float(
                evaluate_expression(
                    expression,
                    scalars=state.scalars,
                    intervals=state.intervals,
                )
            )
        except ExpressionError as exc:
            state.fail(name, "DERIVED_VARIABLE_EVALUATION_FAILED")
            state.record_operation(
                operation_id=name,
                operation_type="derived_variable",
                status="FAIL",
                details={
                    "expression": expression,
                    "error": str(exc),
                },
            )
            return

        state.set_scalar(name, value)
        state.record_operation(
            operation_id=name,
            operation_type="derived_variable",
            status="PASS",
            details={
                "expression": expression,
                "value": value,
            },
        )


def execute_point(
    *,
    plan: Mapping[str, Any],
    model: Mapping[str, Any],
    provider: Any,
    independent_values: Mapping[str, float],
    point_index: int | None = None,
    trace_operations: bool = False,
) -> PropagationState:
    state = _initialize_state(
        independent_values=independent_values,
        plan=plan,
        model=model,
    )

    _evaluate_derived_variables(
        state=state,
        plan=plan,
    )

    if state.status == "FAIL":
        return state

    for operation in plan.get("operations", []) or []:
        if state.status == "FAIL":
            break

        operation_type = str(operation["type"])
        operation_id = str(operation["id"])

        if trace_operations:
            print(
                f"[OP START] point={point_index} "
                f"op={operation_id} type={operation_type}",
                flush=True,
            )

        operation_start = time.perf_counter()

        if operation_type == "technology_range_lookup":
            execute_technology_range_lookup(
                operation,
                state,
                model=model,
                provider=provider,
            )

        elif operation_type in RANGE_OPERATION_HANDLERS:
            execute_range_operation(
                operation,
                state,
            )

        else:
            raise RangeExecutorError(
                f"unsupported schema-v2 operation type "
                f"{operation_type!r}"
            )

        operation_elapsed = time.perf_counter() - operation_start

        state.diagnostics[
            f"{operation_id}_elapsed_s"
        ] = operation_elapsed

        if trace_operations:
            print(
                f"[OP END]   point={point_index} "
                f"op={operation_id} "
                f"elapsed={operation_elapsed:.3f}s "
                f"status={state.status}",
                flush=True,
            )

    return state


def _record_for_outputs(
    *,
    state: PropagationState,
    plan: Mapping[str, Any],
    point_index: int,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "point_index": int(point_index),
        **{
            str(name): float(value)
            for name, value in state.independent_values.items()
        },
        "status": state.status,
        "failure_operation": state.failure_operation,
        "failure_reason": state.failure_reason,
        "last_completed_operation": state.last_completed_operation,
    }

    outputs = plan.get("outputs", {}) or {}

    for name in outputs.get("node_intervals", []) or []:
        interval = state.intervals.get(str(name))
        base = str(name)[:-2] if str(name).endswith("_v") else str(name)
        record[f"{base}_min_v"] = (
            None if interval is None else interval.minimum
        )
        record[f"{base}_max_v"] = (
            None if interval is None else interval.maximum
        )

    for name in outputs.get("device_intervals", []) or []:
        interval = state.intervals.get(str(name))
        record[f"{name}_min"] = (
            None if interval is None else interval.minimum
        )
        record[f"{name}_max"] = (
            None if interval is None else interval.maximum
        )

    for key, value in sorted(state.diagnostics.items()):
        record[str(key)] = value

    return record


def run_design_space(
    *,
    plan_path: Path,
    compiled_model_path: Path,
    independent_regions_path: Path,
    technology_csv_path: Path,
    sample_overrides: Mapping[str, int],
    range_overrides: Mapping[str, tuple[float, float]],
    progress_every: int = 0,
    trace_operations: bool = False,
    witness_resolver: Any | None = None,
    witness_records: list[dict[str, Any]] | None = None,
    witness_failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plan = _load_yaml(plan_path)
    model = _load_json(compiled_model_path)
    independent_regions = _load_json(independent_regions_path)

    if plan.get("artifact") != "openams.dc_propagation_plan":
        raise RangeExecutorError(
            "plan artifact must be openams.dc_propagation_plan"
        )
    if plan.get("schema_version") != 2:
        raise RangeExecutorError(
            "schema-v2 executor requires schema_version=2"
        )
    if plan.get("execution") != "ordered":
        raise RangeExecutorError(
            "schema-v2 executor requires execution=ordered"
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

    provider = InverseFeasibleDatasetProvider(
        technology_csv_path,
        saturation_margin_v=float(
            model["project_inputs"]["design_rules"]
            .get("technology_intersection", {})
            .get("saturation_margin_v", 0.0)
        ),
    )

    records: list[dict[str, Any]] = []

    total_points = 1
    for name in variable_names:
        total_points *= len(values_by_name[name])

    combinations = itertools.product(
        *(values_by_name[name] for name in variable_names)
    )

    run_start = time.perf_counter()

    for point_index, values in enumerate(combinations):
        independent_values = dict(
            zip(variable_names, values)
        )

        point_start = time.perf_counter()

        if trace_operations:
            print(
                f"[POINT START] {point_index + 1}/{total_points} "
                f"{independent_values}",
                flush=True,
            )

        state = execute_point(
            plan=plan,
            model=model,
            provider=provider,
            independent_values=independent_values,
            point_index=point_index,
            trace_operations=trace_operations,
        )

        point_elapsed = time.perf_counter() - point_start
        state.diagnostics["point_elapsed_s"] = point_elapsed

        records.append(
            _record_for_outputs(
                state=state,
                plan=plan,
                point_index=point_index,
            )
        )

        if witness_resolver is not None and state.status == "PASS":
            try:
                witness = witness_resolver(
                    state=state, plan=plan, model=model, provider=provider,
                    point_index=point_index,
                )
                if witness_records is not None:
                    witness_records.append(witness)
            except Exception as exc:
                if witness_failures is not None:
                    witness_failures.append({
                        "point_index": int(point_index),
                        **{str(name): float(value) for name,value in independent_values.items()},
                        "status": "WITNESS_FAIL",
                        "reason": f"{type(exc).__name__}: {exc}",
                    })

        completed = point_index + 1

        if (
            progress_every > 0
            and (
                completed % progress_every == 0
                or completed == total_points
            )
        ):
            elapsed = time.perf_counter() - run_start
            pass_count = sum(
                row["status"] == "PASS"
                for row in records
            )
            fail_count = completed - pass_count

            print(
                f"[PROGRESS] "
                f"{completed}/{total_points} "
                f"({100.0 * completed / total_points:.1f}%) "
                f"PASS={pass_count} FAIL={fail_count} "
                f"last_point={point_elapsed:.3f}s "
                f"elapsed={elapsed:.1f}s "
                f"values={independent_values} "
                f"last_op={state.last_completed_operation} "
                f"failure={state.failure_operation}",
                flush=True,
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
        "artifact": "openams.generic_range_dc_design_space",
        "schema_version": 2,
        "status": "PASS",
        "algorithm": "metadata_ordered_range_propagation",
        "circuit_name": plan.get("circuit_name"),
        "plan": str(plan_path.resolve()),
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
        json.dumps(
            artifact,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    records = list(artifact.get("records", []) or [])
    if not records:
        raise RangeExecutorError(
            "cannot write CSV without records"
        )

    fieldnames = sorted(
        {
            key
            for record in records
            for key in record
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
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(records)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--plan",
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
        "--progress-every",
        type=int,
        default=0,
        help="Print progress after every N independent points.",
    )
    parser.add_argument(
        "--trace-operations",
        action="store_true",
        help="Print every metadata operation start/end for debugging.",
    )
    parser.add_argument("--witness-resolver", default=None, help="Optional MODULE:FUNCTION native-witness resolver.")
    parser.add_argument("--output-witness-jsonl", type=Path, default=None)
    parser.add_argument("--output-witness-failure-jsonl", type=Path, default=None)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    resolver = _load_witness_resolver(args.witness_resolver)
    witnesses: list[dict[str, Any]] = []
    witness_failures: list[dict[str, Any]] = []
    if resolver is None and (args.output_witness_jsonl is not None or args.output_witness_failure_jsonl is not None):
        raise RangeExecutorError("witness output requested without --witness-resolver")

    artifact = run_design_space(
        plan_path=args.plan,
        compiled_model_path=args.compiled_model,
        independent_regions_path=args.independent_regions,
        technology_csv_path=args.technology_csv,
        sample_overrides=_parse_name_int(args.sample),
        range_overrides=_parse_name_range(args.range),
        progress_every=args.progress_every,
        trace_operations=args.trace_operations,
        witness_resolver=resolver,
        witness_records=witnesses,
        witness_failures=witness_failures,
    )

    write_outputs(
        artifact,
        json_path=args.output_json,
        csv_path=args.output_csv,
    )
    if args.output_witness_jsonl is not None:
        _write_jsonl(args.output_witness_jsonl,witnesses)
    if args.output_witness_failure_jsonl is not None:
        _write_jsonl(args.output_witness_failure_jsonl,witness_failures)

    print("===== OPENAMS GENERIC RANGE DC DESIGN SPACE =====")
    print(f"algorithm:          {artifact['algorithm']}")
    print(f"circuit:            {artifact['circuit_name']}")
    print(f"independent points: {artifact['independent_point_count']}")
    print(f"PASS:               {artifact['pass_count']}")
    print(f"FAIL:               {artifact['fail_count']}")
    if resolver is not None:
        print(f"native witnesses:   {len(witnesses)}")
        print(f"witness failures:   {len(witness_failures)}")
    print(f"JSON:               {args.output_json}")
    print(f"CSV:                {args.output_csv}")
    if args.output_witness_jsonl is not None:
        print(f"witness JSONL:      {args.output_witness_jsonl}")
    if args.output_witness_failure_jsonl is not None:
        print(f"witness failure JSONL: {args.output_witness_failure_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

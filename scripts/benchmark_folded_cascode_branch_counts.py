#!/usr/bin/env python3
"""Benchmark folded-cascode branch counts for small and dense technology tables.

This script runs the existing generic Step-5 assignment solver at one fixed
independent-variable point while geometrically increasing the solution cap.
It compares two technology CSV files and stops a table's sweep when the solver
finishes below the requested cap.

The benchmark measures model-valid OpenAMS assignments; it does not run ngspice.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import resource
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass
class RunRecord:
    table_label: str
    technology_csv: str
    cap: int
    assignment_count: int
    independent_point_count: int
    capped: bool
    completed_below_cap: bool
    elapsed_seconds: float
    peak_rss_mb: float
    exact_unique_count: int | None
    exact_duplicate_count: int | None
    status: str
    error: str | None
    output_json: str


def parse_key_value(text: str) -> tuple[str, float]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(
            f"expected NAME=VALUE, received {text!r}"
        )
    name, raw = text.split("=", 1)
    name = name.strip()
    if not name:
        raise argparse.ArgumentTypeError("variable name cannot be empty")
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"value for {name!r} must be numeric"
        ) from exc
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(
            f"value for {name!r} must be finite"
        )
    return name, value


def parse_caps(text: str) -> list[int]:
    caps: list[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            cap = int(token)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid cap {token!r}"
            ) from exc
        if cap <= 0:
            raise argparse.ArgumentTypeError("caps must be positive")
        caps.append(cap)
    if not caps:
        raise argparse.ArgumentTypeError("at least one cap is required")
    if caps != sorted(set(caps)):
        raise argparse.ArgumentTypeError(
            "caps must be unique and strictly increasing"
        )
    return caps


def load_solver(module_name: str) -> Callable[..., Mapping[str, Any]]:
    module = importlib.import_module(module_name)
    function = getattr(module, "build_generic_complete_assignments", None)
    if not callable(function):
        raise RuntimeError(
            f"{module_name!r} does not expose "
            "build_generic_complete_assignments()"
        )
    return function


def peak_rss_mb() -> float:
    # Linux reports ru_maxrss in KiB; macOS reports bytes.
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return value / (1024.0 * 1024.0)
    return value / 1024.0


def normalized_number(value: Any, digits: int = 12) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return round(number, digits)
    return value


def assignment_fingerprint(assignment: Mapping[str, Any]) -> str:
    """Hash the resolved physical state while excluding IDs and row provenance."""
    excluded = {
        "assignment_id",
        "independent_combination_index",
        "solution_index_within_independent_point",
        "device_technology_provenance",
        "route",
        "physical_proof_level",
    }
    canonical: dict[str, Any] = {}
    for key, value in assignment.items():
        if key in excluded:
            continue
        if isinstance(value, (str, bool, int, float)) or value is None:
            canonical[key] = normalized_number(value)
    payload = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def exact_unique_count(result: Mapping[str, Any]) -> int | None:
    assignments = result.get("assignments")
    if not isinstance(assignments, list):
        # Support alternate artifact naming if the solver changes.
        assignments = result.get("complete_assignments")
    if not isinstance(assignments, list):
        return None
    return len(
        {
            assignment_fingerprint(item)
            for item in assignments
            if isinstance(item, Mapping)
        }
    )


def run_once(
    *,
    solver: Callable[..., Mapping[str, Any]],
    table_label: str,
    technology_csv: Path,
    cap: int,
    compiled_model: Path,
    independent_regions: Path,
    dependent_regions: Path,
    fixed_values: Mapping[str, float],
    max_device_candidates: int,
    max_group_choices: int,
    output_dir: Path,
) -> RunRecord:
    run_dir = output_dir / table_label / f"cap_{cap:09d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "complete_assignments.json"

    # min=max and sample count 1 force exactly one independent point.
    range_overrides = {
        name: (value, value) for name, value in fixed_values.items()
    }
    continuous_samples = {name: 1 for name in fixed_values}

    started = time.perf_counter()
    before_rss = peak_rss_mb()
    try:
        result = solver(
            compiled_model,
            independent_regions,
            dependent_regions,
            continuous_samples=continuous_samples,
            range_overrides=range_overrides,
            provider_kind="inverse",
            technology_csv_path=technology_csv,
            max_device_candidates=max_device_candidates,
            max_group_choices=max_group_choices,
            max_solutions_per_independent_point=cap,
            max_assignments=cap,
        )
        elapsed = time.perf_counter() - started

        artifact_path.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        count = int(result.get("complete_assignment_count", 0))
        point_count = int(result.get("independent_combination_count", 1))
        unique = exact_unique_count(result)
        capped = count >= cap

        return RunRecord(
            table_label=table_label,
            technology_csv=str(technology_csv.resolve()),
            cap=cap,
            assignment_count=count,
            independent_point_count=point_count,
            capped=capped,
            completed_below_cap=not capped,
            elapsed_seconds=elapsed,
            peak_rss_mb=max(before_rss, peak_rss_mb()),
            exact_unique_count=unique,
            exact_duplicate_count=(
                None if unique is None else max(0, count - unique)
            ),
            status=str(result.get("status", "UNKNOWN")),
            error=None,
            output_json=str(artifact_path.resolve()),
        )
    except Exception as exc:  # benchmark must preserve partial evidence
        elapsed = time.perf_counter() - started
        error_path = run_dir / "error.txt"
        error_path.write_text(
            f"{type(exc).__name__}: {exc}\n", encoding="utf-8"
        )
        return RunRecord(
            table_label=table_label,
            technology_csv=str(technology_csv.resolve()),
            cap=cap,
            assignment_count=0,
            independent_point_count=1,
            capped=False,
            completed_below_cap=False,
            elapsed_seconds=elapsed,
            peak_rss_mb=max(before_rss, peak_rss_mb()),
            exact_unique_count=None,
            exact_duplicate_count=None,
            status="ERROR",
            error=f"{type(exc).__name__}: {exc}",
            output_json="",
        )


def write_summary(records: list[RunRecord], output_dir: Path) -> None:
    json_path = output_dir / "branch_count_benchmark.json"
    csv_path = output_dir / "branch_count_benchmark.csv"

    payload = {
        "artifact": "openams.folded_cascode_branch_count_benchmark",
        "schema_version": 1,
        "records": [asdict(record) for record in records],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    fieldnames = list(asdict(records[0]).keys()) if records else []
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))

    print(f"\nSummary JSON: {json_path}")
    print(f"Summary CSV:  {csv_path}")


def print_record(record: RunRecord) -> None:
    uniqueness = (
        "n/a"
        if record.exact_unique_count is None
        else f"{record.exact_unique_count:,}"
    )
    print(
        f"[{record.table_label}] cap={record.cap:,} "
        f"assignments={record.assignment_count:,} "
        f"unique={uniqueness} "
        f"capped={'yes' if record.capped else 'no'} "
        f"time={record.elapsed_seconds:.2f}s "
        f"peak_rss={record.peak_rss_mb:.1f}MB "
        f"status={record.status}"
    )
    if record.error:
        print(f"  error: {record.error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate complete folded-cascode assignment counts using small "
            "and dense technology lookup tables."
        )
    )
    parser.add_argument("--compiled-model", type=Path, required=True)
    parser.add_argument("--independent-regions", type=Path, required=True)
    parser.add_argument("--dependent-regions", type=Path, required=True)
    parser.add_argument("--small-table", type=Path, required=True)
    parser.add_argument("--dense-table", type=Path, required=True)
    parser.add_argument(
        "--fixed",
        action="append",
        type=parse_key_value,
        required=True,
        metavar="NAME=VALUE",
        help=(
            "Fix one independent variable. Repeat for every independent "
            "variable, e.g. --fixed i_m3_a=5e-5 --fixed w_m1_um=20 "
            "--fixed vnb1_v=0.7"
        ),
    )
    parser.add_argument(
        "--caps",
        type=parse_caps,
        default=parse_caps("2048,8192,32768,131072,524288"),
        help="Strictly increasing comma-separated caps.",
    )
    parser.add_argument(
        "--max-device-candidates",
        type=int,
        default=512,
        help="Maximum provider candidates retained per device lookup.",
    )
    parser.add_argument(
        "--max-group-choices",
        type=int,
        default=524288,
        help=(
            "Maximum compatible choices retained for each matched-width group. "
            "Keep this at least as large as the largest requested solution cap."
        ),
    )
    parser.add_argument(
        "--solver-module",
        default="openams.synthesis.generic_complete_step5_group_dedup",
        help="Module exposing build_generic_complete_assignments().",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runtime/folded_cascode_branch_count_benchmark"),
    )
    parser.add_argument(
        "--continue-after-complete",
        action="store_true",
        help="Continue higher caps even after a run finishes below its cap.",
    )
    return parser


def validate_paths(paths: list[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit("Missing required files:\n  " + "\n  ".join(missing))


def main() -> int:
    args = build_parser().parse_args()
    validate_paths(
        [
            args.compiled_model,
            args.independent_regions,
            args.dependent_regions,
            args.small_table,
            args.dense_table,
        ]
    )
    if args.max_device_candidates <= 0 or args.max_group_choices <= 0:
        raise SystemExit("candidate and group limits must be positive")

    fixed_values = dict(args.fixed)
    if len(fixed_values) != len(args.fixed):
        raise SystemExit("each --fixed variable may be specified only once")

    args.output.mkdir(parents=True, exist_ok=True)
    configuration = {
        "compiled_model": str(args.compiled_model.resolve()),
        "independent_regions": str(args.independent_regions.resolve()),
        "dependent_regions": str(args.dependent_regions.resolve()),
        "small_table": str(args.small_table.resolve()),
        "dense_table": str(args.dense_table.resolve()),
        "fixed_values": fixed_values,
        "caps": args.caps,
        "max_device_candidates": args.max_device_candidates,
        "max_group_choices": args.max_group_choices,
        "solver_module": args.solver_module,
    }
    (args.output / "benchmark_configuration.json").write_text(
        json.dumps(configuration, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    solver = load_solver(args.solver_module)
    records: list[RunRecord] = []

    for label, table in (
        ("small", args.small_table),
        ("dense", args.dense_table),
    ):
        print(f"\n===== {label.upper()} TABLE =====")
        for cap in args.caps:
            record = run_once(
                solver=solver,
                table_label=label,
                technology_csv=table,
                cap=cap,
                compiled_model=args.compiled_model,
                independent_regions=args.independent_regions,
                dependent_regions=args.dependent_regions,
                fixed_values=fixed_values,
                max_device_candidates=args.max_device_candidates,
                max_group_choices=max(args.max_group_choices, cap),
                output_dir=args.output,
            )
            records.append(record)
            print_record(record)
            write_summary(records, args.output)

            if record.status == "ERROR":
                print(f"Stopping {label} sweep because the run failed.")
                break
            if record.completed_below_cap and not args.continue_after_complete:
                print(
                    f"Stopping {label} sweep: true count is approximately "
                    f"{record.assignment_count:,} for this point."
                )
                break

    print("\n===== FINAL ESTIMATE =====")
    for label in ("small", "dense"):
        table_records = [
            record for record in records
            if record.table_label == label and record.status != "ERROR"
        ]
        if not table_records:
            print(f"{label}: no successful benchmark run")
            continue
        final = table_records[-1]
        if final.capped:
            print(
                f"{label}: at least {final.assignment_count:,} valid "
                f"assignments per tested independent point"
            )
        else:
            print(
                f"{label}: approximately {final.assignment_count:,} valid "
                f"assignments per tested independent point"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

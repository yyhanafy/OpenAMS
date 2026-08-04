#!/usr/bin/env python3
"""Generic backend for run_coarse_independent_ac_scan.py.

The public scan script dispatches here whenever --compiled-model is supplied.
It preserves the two-stage scan's operational contract: progress messages,
checkpointing, exact provider-query counts, per-point runtime, rejection funnel,
CSV output, JSON summary, configuration capture, and resume support.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from openams.synthesis.generic_complete_step5 import (
    _solve_one_independent_point,
    enumerate_independent_domains,
)
from openams.synthesis.mlp_step5_provider import MlpDeviceProvider

SCHEMA_VERSION = "4.0"


def git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def parse_mapping(values: list[str], *, integer: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in values:
        name, separator, raw = item.partition("=")
        if not separator:
            raise SystemExit(f"expected NAME=VALUE, got {item!r}")
        if integer:
            result[name] = int(raw)
        else:
            lower, colon, upper = raw.partition(":")
            if not colon:
                raise SystemExit(f"expected NAME=MIN:MAX, got {item!r}")
            result[name] = (float(lower), float(upper))
    return result


def load_existing(path: Path) -> tuple[list[dict[str, str]], set[int]]:
    if not path.is_file():
        return [], set()
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    return rows, {int(row["grid_index"]) for row in rows}


def flatten_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in assignment.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            row[key] = value
    provenance = assignment.get("device_technology_provenance", {})
    for device, point in provenance.items():
        prefix = str(device).lower()
        for key, value in point.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                row[f"{prefix}_{key}"] = value
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiled-model", type=Path, required=True)
    parser.add_argument("--independent-regions", type=Path, required=True)
    parser.add_argument("--dependent-regions", type=Path, required=True)
    parser.add_argument("--continuous-samples", action="append", default=[])
    parser.add_argument("--range", dest="ranges", action="append", default=[])
    parser.add_argument("--max-device-candidates", type=int, default=64)
    parser.add_argument("--max-points", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mlp-vgs-count", type=int, default=8)
    parser.add_argument("--mlp-vds-count", type=int, default=10)
    args = parser.parse_args(argv)

    samples = parse_mapping(args.continuous_samples, integer=True)
    ranges = parse_mapping(args.ranges)
    model = json.loads(args.compiled_model.read_text(encoding="utf-8"))
    independent = json.loads(args.independent_regions.read_text(encoding="utf-8"))
    names, combinations, values_by_name = enumerate_independent_domains(
        independent,
        continuous_samples=samples,
        range_overrides=ranges,
    )
    if args.max_points > 0:
        combinations = combinations[: args.max_points]

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "coarse_scan_results.csv"
    json_path = output_dir / "coarse_scan_summary.json"
    report_path = output_dir / "COARSE_SCAN_REPORT.md"
    config_path = output_dir / "run_configuration.json"
    adaptive_path = output_dir / "adaptive_mlp_points.csv"

    if csv_path.exists() and not args.resume:
        raise SystemExit(f"refusing to overwrite existing output: {csv_path}; use --resume or a new --output-dir")

    provider = MlpDeviceProvider(
        nmos_checkpoint=Path(os.environ["OPENAMS_MLP_NMOS"]),
        pmos_checkpoint=Path(os.environ["OPENAMS_MLP_PMOS"]),
        adaptive_output=adaptive_path,
        vgs_count=args.mlp_vgs_count,
        vds_count=args.mlp_vds_count,
    )

    config = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "generic_compiled_model_mlp_independent_scan",
        "command": [sys.executable, *sys.argv],
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_status_porcelain": git_value("status", "--porcelain"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "circuit_name": model.get("circuit_name"),
        "compiled_model": str(args.compiled_model.resolve()),
        "independent_regions": str(args.independent_regions.resolve()),
        "dependent_regions": str(args.dependent_regions.resolve()),
        "independent_variable_names": names,
        "independent_values": values_by_name,
        "configured_points": len(combinations),
        "continuous_samples": samples,
        "range_overrides": ranges,
        "device_provider": provider.name,
        "models": {
            "nmos_checkpoint": os.environ["OPENAMS_MLP_NMOS"],
            "pmos_checkpoint": os.environ["OPENAMS_MLP_PMOS"],
        },
    }
    config_path.write_text(json.dumps(config, indent=2, default=str) + "\n", encoding="utf-8")

    existing_rows, completed = load_existing(csv_path) if args.resume else ([], set())
    rows: list[dict[str, Any]] = list(existing_rows)
    failures = Counter(
        row.get("failure", "") for row in existing_rows if row.get("status") != "PASS"
    )

    def save() -> None:
        fields = sorted({key for row in rows for key in row}, key=lambda key: (key not in {"schema_version", "grid_index", "assignment_id", "status", "failure"}, key))
        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    start = time.perf_counter()
    processed_now = 0
    for grid_index, combination in enumerate(combinations):
        if grid_index in completed:
            continue
        independent_values = dict(zip(names, combination, strict=True))
        point_start = time.perf_counter()
        before_queries = provider.query_count
        assignment, rejection = _solve_one_independent_point(
            model,
            provider,
            independent_values,
            max_device_candidates=args.max_device_candidates,
        )
        row: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "grid_index": grid_index,
            "status": "PASS" if assignment is not None else "REJECT",
            "failure": "" if assignment is not None else str(rejection),
            **independent_values,
        }
        if assignment is not None:
            assignment = dict(assignment)
            assignment["assignment_id"] = f"generic_mlp_assignment_{grid_index:06d}"
            row.update(flatten_assignment(assignment))
        else:
            failures[str(rejection)] += 1
        row["mlp_queries_this_point"] = provider.query_count - before_queries
        row["mlp_queries_cumulative"] = provider.query_count
        row["total_runtime_ms"] = (time.perf_counter() - point_start) * 1000.0
        rows.append(row)
        processed_now += 1

        if processed_now % args.checkpoint_every == 0:
            save()
        if processed_now % args.progress_every == 0:
            passed = sum(row.get("status") == "PASS" for row in rows)
            elapsed = time.perf_counter() - start
            print(
                f"[PROGRESS] processed_now={processed_now} "
                f"total_rows={len(rows)}/{len(combinations)} "
                f"pass={passed} reject={len(rows)-passed} "
                f"mlp_queries={provider.query_count} elapsed_s={elapsed:.1f}",
                flush=True,
            )

    save()
    provider.flush()
    elapsed = time.perf_counter() - start
    passed_rows = [row for row in rows if row.get("status") == "PASS"]
    summary = {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
        "algorithm": "generic_compiled_model_mlp_independent_scan",
        "circuit_name": model.get("circuit_name"),
        "grid": {
            "independent_variable_names": names,
            "independent_values": values_by_name,
            "configured_points": len(combinations),
            "points_in_this_output": len(rows),
        },
        "results": {
            "pass_count": len(passed_rows),
            "reject_count": len(rows) - len(passed_rows),
            "mlp_queries": provider.query_count,
            "mlp_queries_per_point": provider.query_count / max(len(rows), 1),
            "failure_counts": dict(failures.most_common()),
            "elapsed_s": elapsed,
            "throughput_points_per_s": len(rows) / max(elapsed, 1e-12),
        },
        "validation": {
            "row_count_matches_grid": len(rows) == len(combinations),
            "unique_grid_indices": len({int(row["grid_index"]) for row in rows}),
        },
        "next_stage": "optional_ac_estimation_or_ngspice_confirmation",
    }
    json_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    report_path.write_text(
        "# Generic Compiled-Model MLP Independent Scan\n\n"
        f"- Circuit: {model.get('circuit_name')}\n"
        f"- Grid points: {len(combinations)}\n"
        f"- Constructed assignments: {len(passed_rows)}\n"
        f"- Rejected points: {len(rows)-len(passed_rows)}\n"
        f"- MLP queries: {provider.query_count}\n"
        f"- MLP queries per point: {provider.query_count / max(len(rows), 1):.3f}\n"
        f"- Elapsed: {elapsed:.3f} s\n"
        f"- Throughput: {len(rows) / max(elapsed, 1e-12):.3f} points/s\n\n"
        "This is the same public scan pipeline used by the frozen two-stage benchmark,\n"
        "with topology and independent variables read from the compiled model.\n",
        encoding="utf-8",
    )

    print("===== OPENAMS COARSE INDEPENDENT SCAN =====")
    print("circuit:", model.get("circuit_name"))
    print("grid points:", len(combinations))
    print("rows completed:", len(rows))
    print("constructed:", len(passed_rows))
    print("rejected:", len(rows) - len(passed_rows))
    print("MLP queries:", provider.query_count)
    print("MLP queries per point:", provider.query_count / max(len(rows), 1))
    print("elapsed_s:", elapsed)
    print("throughput_points_per_s:", len(rows) / max(elapsed, 1e-12))
    print("csv:", csv_path)
    print("json:", json_path)
    print("report:", report_path)
    print("configuration:", config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

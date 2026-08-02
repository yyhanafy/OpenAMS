#!/usr/bin/env python3
"""Validate synthesized two-stage-op-amp assignments before ngspice.

This is Validation Layer 3 of the OpenAMS MVP validation plan.

Checks:
  - required fields and finite numeric values
  - supply and node-voltage bounds
  - differential-pair/current-mirror current relations
  - input-stage KCL
  - voltage definitions and KVL consistency
  - device symmetry
  - width limits
  - M6/M7 width-ratio rule
  - synthesis mismatch/error columns
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_REQUIRED_COLUMNS = {
    "assignment_id",
    "vdd_v",
    "vss_v",
    "vin_cm_v",
    "vtail_v",
    "n1_v",
    "vbias_v",
    "i_m5_a",
    "i_m1_a",
    "i_m2_a",
    "i_m3_a",
    "i_m4_a",
    "w_m5_um",
    "w_m1_um",
    "w_m2_um",
    "w_m3_um",
    "w_m4_um",
    "vgs_m5_v",
    "vds_m5_v",
    "vgs_m1_v",
    "vds_m1_v",
    "vsg_m3_v",
    "vsd_m3_v",
    "tail_node_mismatch_v",
    "n1_node_mismatch_v",
    "vout_v",
    "vsg_m6_v",
    "vsd_m6_v",
    "vgs_m7_v",
    "vds_m7_v",
    "i_m6_a",
    "i_m7_a",
    "w_m6_um",
    "w_m7_um",
    "required_w6_over_w7",
    "actual_w6_over_w7",
    "width_relation_relative_error",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assignments",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/"
            "assignment_synthesis/complete_assignments.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime/validation/two_stage_opamp/layer3"),
    )
    parser.add_argument("--current-abs-tol-a", type=float, default=1.0e-6)
    parser.add_argument("--current-rel-tol", type=float, default=0.10)
    parser.add_argument("--voltage-tol-v", type=float, default=0.025)
    parser.add_argument("--electrical-tol-v", type=float, default=1.0e-9)
    parser.add_argument("--width-rel-tol", type=float, default=1.0e-8)
    parser.add_argument("--width-min-um", type=float, default=0.42)
    parser.add_argument("--width-max-um", type=float, default=100.0)
    return parser.parse_args()


def number(row: dict[str, str], name: str) -> float:
    raw = row.get(name, "")
    if raw is None or not str(raw).strip():
        raise ValueError(f"missing numeric value: {name}")

    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric value: {name}={raw!r}")

    return value


def residual_pass(
    actual: float,
    expected: float,
    *,
    abs_tol: float,
    rel_tol: float = 0.0,
) -> tuple[bool, float, float]:
    residual = actual - expected
    tolerance = max(abs_tol, rel_tol * max(abs(actual), abs(expected)))
    return abs(residual) <= tolerance, residual, tolerance


def add_check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    passed: bool,
    actual: Any,
    expected: Any,
    residual: Any = None,
    tolerance: Any = None,
    category: str,
) -> None:
    checks.append(
        {
            "check": name,
            "category": category,
            "passed": bool(passed),
            "actual": actual,
            "expected": expected,
            "residual": residual,
            "tolerance": tolerance,
        }
    )


def validate_row(
    row: dict[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    assignment_id = row.get("assignment_id", "").strip() or "<missing>"

    try:
        values = {
            name: number(row, name)
            for name in DEFAULT_REQUIRED_COLUMNS
            if name != "assignment_id"
        }
    except (TypeError, ValueError) as exc:
        return {
            "assignment_id": assignment_id,
            "passed": False,
            "primary_failure": "MISSING_OR_INVALID_VALUE",
            "checks": [
                {
                    "check": "numeric_fields",
                    "category": "structure",
                    "passed": False,
                    "actual": str(exc),
                    "expected": "all required numeric fields present and finite",
                    "residual": None,
                    "tolerance": None,
                }
            ],
        }

    v = values

    # --------------------------------------------------------------
    # Supply and node bounds
    # --------------------------------------------------------------
    add_check(
        checks,
        name="supply_order",
        passed=v["vdd_v"] > v["vss_v"],
        actual=v["vdd_v"] - v["vss_v"],
        expected="> 0",
        category="voltage_bounds",
    )

    for node in ("vin_cm_v", "vtail_v", "n1_v", "vbias_v", "vout_v"):
        passed = (
            v["vss_v"] - args.voltage_tol_v
            <= v[node]
            <= v["vdd_v"] + args.voltage_tol_v
        )
        add_check(
            checks,
            name=f"{node}_inside_rails",
            passed=passed,
            actual=v[node],
            expected=f"[{v['vss_v']}, {v['vdd_v']}]",
            tolerance=args.voltage_tol_v,
            category="voltage_bounds",
        )

    # --------------------------------------------------------------
    # Current relations and KCL
    # i_m1 = i_m2 = i_m3 = i_m4 = i_m5 / 2
    # --------------------------------------------------------------
    branch_target = v["i_m5_a"] / 2.0

    for name in ("i_m1_a", "i_m2_a", "i_m3_a", "i_m4_a"):
        passed, residual, tolerance = residual_pass(
            v[name],
            branch_target,
            abs_tol=args.current_abs_tol_a,
            rel_tol=args.current_rel_tol,
        )
        add_check(
            checks,
            name=f"{name}_equals_half_i_m5",
            passed=passed,
            actual=v[name],
            expected=branch_target,
            residual=residual,
            tolerance=tolerance,
            category="current_relation",
        )

    # Tail-node KCL: I5 = I1 + I2
    passed, residual, tolerance = residual_pass(
        v["i_m5_a"],
        v["i_m1_a"] + v["i_m2_a"],
        abs_tol=args.current_abs_tol_a,
        rel_tol=args.current_rel_tol,
    )
    add_check(
        checks,
        name="tail_node_kcl",
        passed=passed,
        actual=v["i_m5_a"],
        expected=v["i_m1_a"] + v["i_m2_a"],
        residual=residual,
        tolerance=tolerance,
        category="kcl",
    )

    # N1 branch KCL: I1 = I3
    passed, residual, tolerance = residual_pass(
        v["i_m1_a"],
        v["i_m3_a"],
        abs_tol=args.current_abs_tol_a,
        rel_tol=args.current_rel_tol,
    )
    add_check(
        checks,
        name="n1_branch_kcl",
        passed=passed,
        actual=v["i_m1_a"],
        expected=v["i_m3_a"],
        residual=residual,
        tolerance=tolerance,
        category="kcl",
    )

    # Output node DC KCL: I6 = I7
    passed, residual, tolerance = residual_pass(
        v["i_m6_a"],
        v["i_m7_a"],
        abs_tol=args.current_abs_tol_a,
        rel_tol=args.current_rel_tol,
    )
    add_check(
        checks,
        name="output_node_kcl",
        passed=passed,
        actual=v["i_m6_a"],
        expected=v["i_m7_a"],
        residual=residual,
        tolerance=tolerance,
        category="kcl",
    )

    # --------------------------------------------------------------
    # Voltage definitions / KVL
    # --------------------------------------------------------------
    voltage_equations = {
        "vgs_m5_definition": (
            v["vgs_m5_v"],
            v["vbias_v"] - v["vss_v"],
        ),
        "vds_m5_definition": (
            v["vds_m5_v"],
            v["vtail_v"] - v["vss_v"],
        ),
        "vgs_m1_definition": (
            v["vgs_m1_v"],
            v["vin_cm_v"] - v["vtail_v"],
        ),
        "vds_m1_definition": (
            v["vds_m1_v"],
            v["n1_v"] - v["vtail_v"],
        ),
        "vsg_m3_definition": (
            v["vsg_m3_v"],
            v["vdd_v"] - v["n1_v"],
        ),
        "vsd_m3_definition": (
            v["vsd_m3_v"],
            v["vdd_v"] - v["n1_v"],
        ),
        "vsg_m6_definition": (
            v["vsg_m6_v"],
            v["vdd_v"] - v["n1_v"],
        ),
        "vsd_m6_definition": (
            v["vsd_m6_v"],
            v["vdd_v"] - v["vout_v"],
        ),
        "vgs_m7_definition": (
            v["vgs_m7_v"],
            v["vbias_v"] - v["vss_v"],
        ),
        "vds_m7_definition": (
            v["vds_m7_v"],
            v["vout_v"] - v["vss_v"],
        ),
    }

    for name, (actual, expected) in voltage_equations.items():
        passed, residual, tolerance = residual_pass(
            actual,
            expected,
            abs_tol=args.electrical_tol_v,
        )
        add_check(
            checks,
            name=name,
            passed=passed,
            actual=actual,
            expected=expected,
            residual=residual,
            tolerance=tolerance,
            category="kvl",
        )

    # --------------------------------------------------------------
    # Synthesis-reported voltage mismatches
    # --------------------------------------------------------------
    for name in ("tail_node_mismatch_v", "n1_node_mismatch_v"):
        passed = abs(v[name]) <= args.voltage_tol_v
        add_check(
            checks,
            name=f"{name}_within_tolerance",
            passed=passed,
            actual=v[name],
            expected=0.0,
            residual=v[name],
            tolerance=args.voltage_tol_v,
            category="synthesis_residual",
        )

    # --------------------------------------------------------------
    # Device symmetry
    # --------------------------------------------------------------
    for left, right in (
        ("w_m1_um", "w_m2_um"),
        ("w_m3_um", "w_m4_um"),
    ):
        passed, residual, tolerance = residual_pass(
            v[left],
            v[right],
            abs_tol=1.0e-12,
            rel_tol=args.width_rel_tol,
        )
        add_check(
            checks,
            name=f"{left}_equals_{right}",
            passed=passed,
            actual=v[left],
            expected=v[right],
            residual=residual,
            tolerance=tolerance,
            category="symmetry",
        )

    # --------------------------------------------------------------
    # Width bounds
    # --------------------------------------------------------------
    for name in (
        "w_m1_um",
        "w_m2_um",
        "w_m3_um",
        "w_m4_um",
        "w_m5_um",
        "w_m6_um",
        "w_m7_um",
    ):
        passed = args.width_min_um <= v[name] <= args.width_max_um
        add_check(
            checks,
            name=f"{name}_inside_limits",
            passed=passed,
            actual=v[name],
            expected=f"[{args.width_min_um}, {args.width_max_um}]",
            category="technology_constraint",
        )

    # --------------------------------------------------------------
    # Width-ratio relation
    # --------------------------------------------------------------
    computed_ratio = v["w_m6_um"] / v["w_m7_um"]

    passed, residual, tolerance = residual_pass(
        v["actual_w6_over_w7"],
        computed_ratio,
        abs_tol=1.0e-12,
        rel_tol=args.width_rel_tol,
    )
    add_check(
        checks,
        name="stored_actual_width_ratio",
        passed=passed,
        actual=v["actual_w6_over_w7"],
        expected=computed_ratio,
        residual=residual,
        tolerance=tolerance,
        category="width_relation",
    )

    ratio_error = abs(
        v["actual_w6_over_w7"] - v["required_w6_over_w7"]
    ) / max(abs(v["required_w6_over_w7"]), 1.0e-30)

    passed = ratio_error <= args.width_rel_tol
    add_check(
        checks,
        name="required_w6_over_w7_relation",
        passed=passed,
        actual=v["actual_w6_over_w7"],
        expected=v["required_w6_over_w7"],
        residual=ratio_error,
        tolerance=args.width_rel_tol,
        category="width_relation",
    )

    passed, residual, tolerance = residual_pass(
        v["width_relation_relative_error"],
        ratio_error,
        abs_tol=1.0e-12,
        rel_tol=args.width_rel_tol,
    )
    add_check(
        checks,
        name="stored_width_relation_error",
        passed=passed,
        actual=v["width_relation_relative_error"],
        expected=ratio_error,
        residual=residual,
        tolerance=tolerance,
        category="width_relation",
    )

    failures = [check for check in checks if not check["passed"]]

    category_priority = (
        "structure",
        "kcl",
        "kvl",
        "current_relation",
        "voltage_bounds",
        "technology_constraint",
        "symmetry",
        "width_relation",
        "synthesis_residual",
    )

    primary_failure = None
    for category in category_priority:
        match = next(
            (
                check["check"]
                for check in failures
                if check["category"] == category
            ),
            None,
        )
        if match:
            primary_failure = match
            break

    return {
        "assignment_id": assignment_id,
        "passed": not failures,
        "primary_failure": primary_failure,
        "failed_check_count": len(failures),
        "check_count": len(checks),
        "checks": checks,
    }


def main() -> int:
    args = parse_args()

    if not args.assignments.is_file():
        raise SystemExit(
            f"Assignments CSV does not exist: {args.assignments}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with args.assignments.open(newline="") as handle:
        reader = csv.DictReader(handle)

        if reader.fieldnames is None:
            raise SystemExit("Assignments CSV has no header")

        missing_columns = sorted(
            DEFAULT_REQUIRED_COLUMNS - set(reader.fieldnames)
        )
        if missing_columns:
            raise SystemExit(
                "Assignments CSV is missing required columns: "
                + ", ".join(missing_columns)
            )

        results = [validate_row(row, args) for row in reader]

    pass_count = sum(result["passed"] for result in results)
    fail_count = len(results) - pass_count

    failure_counts = Counter(
        result["primary_failure"]
        for result in results
        if result["primary_failure"]
    )

    summary = {
        "validation_layer": 3,
        "validation_name": "circuit_assignment_consistency",
        "input": str(args.assignments),
        "assignment_count": len(results),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": (
            pass_count / len(results) if results else 0.0
        ),
        "all_assignments_passed": fail_count == 0 and bool(results),
        "primary_failure_counts": dict(failure_counts),
        "tolerances": {
            "current_absolute_tolerance_a": args.current_abs_tol_a,
            "current_relative_tolerance": args.current_rel_tol,
            "voltage_tolerance_v": args.voltage_tol_v,
            "electrical_voltage_tolerance_v": args.electrical_tol_v,
            "width_relation_relative_tolerance": args.width_rel_tol,
            "width_min_um": args.width_min_um,
            "width_max_um": args.width_max_um,
        },
    }

    report = {
        "summary": summary,
        "assignments": results,
    }

    report_path = args.output_dir / "assignment_validation_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    csv_path = args.output_dir / "assignment_validation_summary.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "assignment_id",
                "passed",
                "check_count",
                "failed_check_count",
                "primary_failure",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "assignment_id": result["assignment_id"],
                    "passed": result["passed"],
                    "check_count": result.get("check_count", 0),
                    "failed_check_count": result.get(
                        "failed_check_count", 1
                    ),
                    "primary_failure": result["primary_failure"] or "",
                }
            )

    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    print("===== OPENAMS VALIDATION LAYER 3 =====")
    print(f"input:       {args.assignments}")
    print(f"assignments: {len(results)}")
    print(f"passed:      {pass_count}")
    print(f"failed:      {fail_count}")
    print(f"report:      {report_path}")
    print(f"summary:     {summary_path}")
    print(f"table:       {csv_path}")

    if failure_counts:
        print("\nPrimary failures:")
        for name, count in failure_counts.most_common():
            print(f"  {name}: {count}")

    if not results:
        print("[FAIL] No assignments were found.")
        return 2

    if fail_count:
        print("[FAIL] Layer 3 assignment validation failed.")
        return 1

    print("[PASS] All assignments are internally consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

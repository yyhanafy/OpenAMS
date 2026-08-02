#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path("examples/two_stage_opamp/generated/assignment_synthesis")
ASSIGNMENTS = ROOT / "complete_assignments.json"
TECHNOLOGY = Path("technology/sky130_tt_27c_inverse_smoke.csv")
OUTPUT = ROOT / "saturation_audit.json"

# Use 0.0 for the table's saturation criterion.
# Use 0.05 for an additional 50 mV design margin.
REQUIRED_MARGIN_V = 0.0


def number(value: Any) -> float:
    return float(value)


def load_technology(path: Path) -> dict[int, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {
            index: row
            for index, row in enumerate(csv.DictReader(stream))
        }


def row_margin(row: dict[str, str]) -> float:
    vds = number(row["vds_abs_v"])
    vdsat = number(row["vdsat_abs_v"])
    return vds - vdsat


def main() -> int:
    artifact = json.loads(ASSIGNMENTS.read_text(encoding="utf-8"))
    assignments = artifact["assignments"]
    technology = load_technology(TECHNOLOGY)

    failures = Counter()
    minimum_margin = {
        f"M{device}": float("inf")
        for device in range(1, 8)
    }
    failed_examples: list[dict[str, Any]] = []

    exact_row_fields = {
        "M1": "m1_technology_row_index",
        "M3": "m3_technology_row_index",
        "M4": "m4_technology_row_index",
        "M5": "m5_technology_row_index",
        "M7": "m7_technology_row_index",
    }

    for assignment in assignments:
        assignment_failures = []

        # Exact table-backed devices.
        for device, field in exact_row_fields.items():
            row_index = int(assignment[field])
            row = technology[row_index]

            saturated_flag = (
                str(row["saturated"]).strip().lower()
                in {"1", "true", "yes"}
            )
            margin = row_margin(row)
            minimum_margin[device] = min(
                minimum_margin[device],
                margin,
            )

            if not saturated_flag or margin < REQUIRED_MARGIN_V:
                failures[device] += 1
                assignment_failures.append(
                    {
                        "device": device,
                        "technology_row": row_index,
                        "margin_v": margin,
                        "saturated_flag": saturated_flag,
                    }
                )

        # M2 inherits the M1 operating point.
        m1_row = technology[
            int(assignment["m1_technology_row_index"])
        ]
        m2_margin = row_margin(m1_row)
        minimum_margin["M2"] = min(
            minimum_margin["M2"],
            m2_margin,
        )

        if (
            str(m1_row["saturated"]).strip().lower()
            not in {"1", "true", "yes"}
            or m2_margin < REQUIRED_MARGIN_V
        ):
            failures["M2"] += 1
            assignment_failures.append(
                {
                    "device": "M2",
                    "technology_row": int(
                        assignment["m1_technology_row_index"]
                    ),
                    "margin_v": m2_margin,
                }
            )

        # M6 is interpolated between two saturated technology rows.
        lower_index = int(
            assignment["m6_lower_technology_row_index"]
        )
        upper_index = int(
            assignment["m6_upper_technology_row_index"]
        )
        alpha = number(
            assignment["m6_interpolation_fraction"]
        )

        lower = technology[lower_index]
        upper = technology[upper_index]

        lower_vdsat = number(lower["vdsat_abs_v"])
        upper_vdsat = number(upper["vdsat_abs_v"])

        interpolated_vdsat = (
            lower_vdsat
            + alpha * (upper_vdsat - lower_vdsat)
        )

        m6_vds = number(assignment["m6_vds_v"])
        m6_margin = m6_vds - interpolated_vdsat

        minimum_margin["M6"] = min(
            minimum_margin["M6"],
            m6_margin,
        )

        endpoint_saturated = all(
            str(row["saturated"]).strip().lower()
            in {"1", "true", "yes"}
            for row in (lower, upper)
        )

        if (
            not endpoint_saturated
            or not 0.0 <= alpha <= 1.0
            or m6_margin < REQUIRED_MARGIN_V
        ):
            failures["M6"] += 1
            assignment_failures.append(
                {
                    "device": "M6",
                    "lower_row": lower_index,
                    "upper_row": upper_index,
                    "interpolation_fraction": alpha,
                    "vds_v": m6_vds,
                    "interpolated_vdsat_v": interpolated_vdsat,
                    "margin_v": m6_margin,
                    "endpoint_saturated": endpoint_saturated,
                }
            )

        if assignment_failures and len(failed_examples) < 100:
            failed_examples.append(
                {
                    "assignment_id": assignment["assignment_id"],
                    "failures": assignment_failures,
                }
            )

    total_failures = sum(failures.values())

    report = {
        "artifact": "openams.assignment_saturation_audit",
        "assignments_checked": len(assignments),
        "transistor_checks": len(assignments) * 7,
        "required_margin_v": REQUIRED_MARGIN_V,
        "status": "PASS" if total_failures == 0 else "FAIL",
        "failure_counts": dict(failures),
        "total_device_failures": total_failures,
        "minimum_margin_v_by_device": minimum_margin,
        "failed_examples": failed_examples,
    }

    OUTPUT.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    print("===== OPENAMS SATURATION AUDIT =====")
    print("status:", report["status"])
    print("assignments checked:", len(assignments))
    print("transistor checks:", len(assignments) * 7)

    for device in range(1, 8):
        name = f"M{device}"
        print(
            f"{name}: failures={failures[name]} "
            f"minimum_margin_v={minimum_margin[name]:.6g}"
        )

    print("total device failures:", total_failures)
    print("report:", OUTPUT)

    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

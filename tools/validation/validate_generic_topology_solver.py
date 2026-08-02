#!/usr/bin/env python3
"""Validate fully populated assignments from the generic solver."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openams.synthesis.generic_topology_solver import write_generic_assignments


def main() -> int:
    parser = argparse.ArgumentParser()
    base = Path("examples/two_stage_opamp/generated")
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=base / "compiled_circuit_model.json",
    )
    parser.add_argument(
        "--independent-regions",
        type=Path,
        default=base / "assignment_synthesis/independent_regions.json",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=base / "generic_assignment_contract.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=base / "assignment_synthesis/generic_assignments_smoke.json",
    )
    parser.add_argument("--max-solutions", type=int, default=25)
    parser.add_argument("--max-partials", type=int, default=50000)
    parser.add_argument("--progress-every", type=int, default=1000)
    args = parser.parse_args()

    artifact = write_generic_assignments(
        args.compiled_model,
        args.independent_regions,
        args.contract,
        args.output,
        max_solutions=args.max_solutions,
        max_partials=args.max_partials,
        progress_every=args.progress_every,
    )

    assignments = artifact["assignments"]
    required = {
        *(f"i_m{index}_a" for index in range(1, 8)),
        *(f"w_m{index}_um" for index in range(1, 8)),
        "vtail_v", "n1_v", "n2_v", "vbias_v", "vout_v",
        *(f"nf_m{index}" for index in range(1, 8)),
        *(f"w_finger_m{index}_um" for index in range(1, 8)),
    }

    checks = {
        "status_pass": artifact["status"] == "PASS",
        "solutions_exist": artifact["assignment_count"] > 0,
        "generic_solver": (
            artifact["solver"]
            == "generic_constraint_propagating_backtracking"
        ),
        "no_topology_specific_code": (
            artifact["topology_specific_code"] is False
        ),
        "all_devices_assigned": all(
            row["device_row_count"] == 7
            for row in assignments
        ),
        "all_required_quantities_present": all(
            required <= set(row)
            for row in assignments
        ),
        "output_currents_equal": all(
            row["i_m6_a"] == row["i_m7_a"]
            for row in assignments
        ),
        "matched_widths": all(
            row["w_m2_um"] == row["w_m1_um"]
            and row["w_m4_um"] == row["w_m3_um"]
            for row in assignments
        ),
        "m6_interpolation_present": all(
            "m6_lower_technology_row_index" in row
            and "m6_upper_technology_row_index" in row
            and "m6_interpolation_fraction" in row
            for row in assignments
        ),
    }
    passed = all(checks.values())

    print("===== OPENAMS GENERIC TOPOLOGY SOLVER V2 =====")
    print(f"status:        {'PASS' if passed else 'FAIL'}")
    print(f"solutions:     {artifact['assignment_count']}")
    print(f"partials:      {artifact['statistics']['partials']}")
    print(f"early rejects: {artifact['statistics']['early_rejections']}")
    print(f"stop reason:   {artifact.get('stop_reason')}")
    print(f"output:        {args.output}")

    diagnostics = artifact.get("diagnostics", {})
    print("\n===== SEARCH DIAGNOSTICS =====")
    print(
        "technology rows by device:",
        diagnostics.get("technology_rows_by_device", {}),
    )
    print(
        "partials by assigned-device count:",
        artifact["statistics"].get(
            "partials_by_assigned_device_count", {}
        ),
    )
    print(
        "dead ends by next device:",
        artifact["statistics"].get(
            "dead_end_by_next_device", {}
        ),
    )

    print("\nTop rejecting constraints:")
    for name, count in list(
        diagnostics.get("rejection_by_constraint", {}).items()
    )[:15]:
        print(f"  {name}: {count}")

    print("\nTop device/constraint trial rejections:")
    for name, count in list(
        diagnostics.get("rejection_by_device_trial", {}).items()
    )[:20]:
        print(f"  {name}: {count}")

    missing_sets = artifact["statistics"].get(
        "missing_complete_quantity_sets", {}
    )
    if missing_sets:
        print("\nMissing quantities at nominal completion:")
        for names, count in list(missing_sets.items())[:10]:
            print(f"  {count}: {names}")

    if not passed:
        print(json.dumps(checks, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

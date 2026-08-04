#!/usr/bin/env python3
"""Validate physically bounded, correlated Step 4 dependent regions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openams.synthesis.dependent_regions import write_dependent_regions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/compiled_circuit_model.json"
        ),
    )
    parser.add_argument(
        "--independent-regions",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/assignment_synthesis/"
            "independent_regions.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/assignment_synthesis/"
            "dependent_regions.json"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/assignment_synthesis/"
            "STEP4_DEPENDENT_REGIONS_REPORT.md"
        ),
    )
    args = parser.parse_args()

    artifact = write_dependent_regions(
        args.compiled_model,
        args.independent_regions,
        args.output,
    )
    regions = artifact["dependent_regions"]
    output_group = next(
        group for group in artifact["groups"]
        if group["group_id"] == "output_stage"
    )
    correlated = output_group["correlated_candidates"]

    checks = {
        "status_pass": artifact["status"] == "PASS",
        "no_missing_declared_quantities": not artifact["missing_declared_quantities"],
        "two_groups_executed": len(artifact["groups"]) == 2,
        "n2_explicitly_derived": "n2_v" in regions,
        "all_intervals_nonempty": all(
            value["minimum"] <= value["maximum"]
            for value in regions.values()
        ),
        "vtail_not_below_vss": regions["vtail_v"]["minimum"] >= 0.0,
        "correlated_output_candidates_exist": len(correlated) > 0,
        "every_output_candidate_current_balanced": all(
            row["i_m6_a"] == row["i_m7_a"]
            for row in correlated
        ),
        "every_output_candidate_vout_bounded": all(
            0.6 <= row["vout_v"] <= 1.5
            for row in correlated
        ),
        "every_output_candidate_width_legal": all(
            0.42 <= row["w_finger_m6_um"] <= 100.0
            and 0.42 <= row["w_finger_m7_um"] <= 100.0
            and 1 <= row["nf_m6"] <= 3
            and 1 <= row["nf_m7"] <= 3
            for row in correlated
        ),
        "next_stage_correct": (
            artifact["next_stage"] == "intersect_complete_dc_assignments"
        ),
    }
    passed = all(checks.values())

    compact = {
        name: {
            "minimum": value["minimum"],
            "maximum": value["maximum"],
        }
        for name, value in regions.items()
    }
    report = (
        "# Assignment Synthesis Step 4 Report\n\n"
        f"**Status:** {'PASS' if passed else 'FAIL'}\n\n"
        f"- Correlated output-stage candidates: {len(correlated)}\n\n"
        "## Derived Regions\n\n```json\n"
        + json.dumps(compact, indent=2)
        + "\n```\n\n## Checks\n\n```json\n"
        + json.dumps(checks, indent=2)
        + "\n```\n"
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")

    print("===== OPENAMS ASSIGNMENT STEP 4: DEPENDENT REGIONS =====")
    print(f"status:       {'PASS' if passed else 'FAIL'}")
    print(f"groups:       {len(artifact['groups'])}")
    print(f"regions:      {len(regions)}")
    print(f"missing:      {artifact['missing_declared_quantities'] or 'none'}")
    print(f"output tuples:{len(correlated)}")
    for name, value in compact.items():
        print(f"{name}: [{value['minimum']}, {value['maximum']}]")
    print(f"output:       {args.output}")
    print(f"report:       {args.report}")

    if not passed:
        for name, value in checks.items():
            if not value:
                print(f"[FAIL] {name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

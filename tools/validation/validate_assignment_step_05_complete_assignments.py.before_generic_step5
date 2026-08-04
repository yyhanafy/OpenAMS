#!/usr/bin/env python3
"""Validate indexed/interpolated Step 5 complete assignments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openams.synthesis.complete_assignments import write_complete_assignments


def main() -> int:
    parser = argparse.ArgumentParser()
    base = Path("examples/two_stage_opamp/generated/assignment_synthesis")
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=Path("examples/two_stage_opamp/generated/compiled_circuit_model.json"),
    )
    parser.add_argument("--independent-regions", type=Path, default=base / "independent_regions.json")
    parser.add_argument("--dependent-regions", type=Path, default=base / "dependent_regions.json")
    parser.add_argument("--output-json", type=Path, default=base / "complete_assignments.json")
    parser.add_argument("--output-csv", type=Path, default=base / "complete_assignments.csv")
    parser.add_argument("--report", type=Path, default=base / "STEP5_COMPLETE_ASSIGNMENTS_REPORT.md")
    args = parser.parse_args()

    artifact = write_complete_assignments(
        args.compiled_model,
        args.independent_regions,
        args.dependent_regions,
        args.output_json,
        args.output_csv,
    )
    assignments = artifact["assignments"]

    checks = {
        "status_pass": artifact["status"] == "PASS",
        "input_candidates_exist": artifact["input_bias_candidate_count"] > 0,
        "complete_assignments_exist": artifact["complete_assignment_count"] > 0,
        "direct_simulation_route": artifact["recommended_route"] == "direct_simulation",
        "all_current_balanced": all(row["i_m6_a"] == row["i_m7_a"] for row in assignments),
        "all_size_relations_exact": all(
            row["second_stage_ratio_relative_error"] <= 1e-12
            for row in assignments
        ),
        "all_nodes_physical": all(
            0.0 <= row["vtail_v"] <= 0.9
            and 0.0 <= row["n1_v"] <= 1.8
            and 0.0 <= row["n2_v"] <= 1.8
            and 0.0 <= row["vbias_v"] <= 1.8
            and 0.2 <= row["vout_v"] <= 1.6
            for row in assignments
        ),
        "interpolation_provenance_present": all(
            "m6_lower_technology_row_index" in row
            and "m6_upper_technology_row_index" in row
            for row in assignments
        ),
    }
    passed = all(checks.values())

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        "# Assignment Synthesis Step 5 Report\n\n"
        f"**Status:** {'PASS' if passed else 'FAIL'}\n\n"
        f"- Algorithm: `{artifact['algorithm']}`\n"
        f"- Input-bias candidates: {artifact['input_bias_candidate_count']}\n"
        f"- Step 4 output candidates: {artifact['step4_output_candidate_count']}\n"
        f"- Complete assignments: {artifact['complete_assignment_count']}\n"
        f"- Route: `{artifact['recommended_route']}`\n\n"
        "## Checks\n\n```json\n"
        + json.dumps(checks, indent=2)
        + "\n```\n\n## Rejections\n\n```json\n"
        + json.dumps(
            {
                "input": artifact["input_rejection_counts"],
                "join": artifact["join_rejection_counts"],
            },
            indent=2,
        )
        + "\n```\n",
        encoding="utf-8",
    )

    print("===== OPENAMS ASSIGNMENT STEP 5: COMPLETE DC ASSIGNMENTS =====")
    print(f"status:           {'PASS' if passed else 'FAIL'}")
    print(f"algorithm:        {artifact['algorithm']}")
    print(f"input candidates: {artifact['input_bias_candidate_count']}")
    print(f"assignments:      {artifact['complete_assignment_count']}")
    print(f"route:            {artifact['recommended_route']}")
    print(f"json:             {args.output_json}")
    print(f"csv:              {args.output_csv}")
    print(f"report:           {args.report}")

    if not passed:
        for name, value in checks.items():
            if not value:
                print(f"[FAIL] {name}")
        print(json.dumps(artifact["join_rejection_counts"], indent=2))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

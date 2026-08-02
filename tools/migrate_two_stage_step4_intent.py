#!/usr/bin/env python3
"""Add the explicit Step 4 dependent-region contract to design intent."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--intent",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs/design_intent.yaml"),
    )
    args = parser.parse_args()

    data = yaml.safe_load(args.intent.read_text(encoding="utf-8"))
    parameterization = data["synthesis_parameterization"]
    dependent = parameterization["dependent_quantities"]
    if "n2_v" not in dependent:
        index = dependent.index("n1_v") + 1 if "n1_v" in dependent else len(dependent)
        dependent.insert(index, "n2_v")

    parameterization["dependent_width_realization"] = {
        "total_width_min_um": 0.42,
        "total_width_max_um": 300.0,
        "finger_width_min_um": 0.42,
        "finger_width_max_um": 100.0,
        "nf_min": 1,
        "nf_max": 3,
        "scaling_model": "linear_current_scaling",
    }

    data["dependent_derivation_contract"] = {
        "semantics": "group_ordered_technology_backed_regions",
        "technology_interpolation": "linear_total_width_scaling",
        "groups": {
            "input_bias_network": {
                "solver": "two_stage_input_bias_adapter",
                "derives": [
                    "i_m1_a", "i_m2_a", "i_m3_a", "i_m4_a",
                    "w_m2_um", "w_m3_um", "w_m4_um", "w_m5_um",
                    "vtail_v", "n1_v", "n2_v", "vbias_v",
                ],
            },
            "output_stage": {
                "solver": "two_stage_output_stage_adapter",
                "depends_on": ["input_bias_network"],
                "derives": ["i_m6_a", "i_m7_a", "w_m6_um", "w_m7_um"],
                "deferred_constraints": [
                    "second_stage_size_relation",
                    "complete_assignment_intersection",
                ],
            },
        },
    }

    backup = args.intent.with_name(args.intent.name + ".before_step4_contract")
    if not backup.exists():
        shutil.copy2(args.intent, backup)

    args.intent.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    print(f"[PASS] updated {args.intent}")
    print(f"[PASS] backup  {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

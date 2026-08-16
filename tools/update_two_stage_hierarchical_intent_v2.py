#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intent", required=True, type=Path)
    args = ap.parse_args()

    data = yaml.safe_load(args.intent.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("design_intent.yaml must be a mapping")

    data["hierarchical_feasibility"] = {
        "schema_version": 2,
        "strategy": "hierarchical_component_mlp_exact_realization",
        "independent_point_source": {
            "kind": "independent_regions_json",
            "path": "examples/two_stage_opamp/generated/assignment_synthesis/independent_regions.json",
            "variables": {
                "w_m1_um": {
                    "domain": "w_m1_um",
                    "sampling": "linear_from_domain",
                    "count": 25,
                },
                "i_m5_a": {
                    "domain": "i_m5_a",
                    "sampling": "candidate_values",
                },
            },
        },
        "components": [
            {
                "id": "input_bias_network",
                "source_group": "input_bias_network",
                "checkpoint":
                    "technology/component_models/two_stage_input_bias_network_v3.pt",
                "model_kind": "feasibility_range_emitter",
                "mlp_features": [
                    "w_m1_um",
                    "i_m5_a",
                    "vy_v",
                    "vbias_v",
                ],
                "interface_inputs": [],
                "interface_outputs": ["first_second_stage_cut"],
                "emitted_ranges": [
                    {
                        "name": "stage_ratio",
                        "low_output": "log_r_min",
                        "high_output": "log_r_max",
                        "transform": "exp",
                    }
                ],
                "exact_realizer": {
                    "driver": "witness_plan_builder",
                    "module":
                        "tools/validation/run_two_stage_independent_tables_v2.py",
                    "builder_function": "build_a_plan",
                    "base_plan":
                        "examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml",
                    "witnesses_per_state": 5,
                },
                "derived_after_realization": [
                    {
                        "name": "stage_ratio",
                        "expression": "2.0 * w_m3_um / w_m5_um",
                    }
                ],
            },
            {
                "id": "output_stage",
                "source_group": "output_stage",
                "depends_on": ["input_bias_network"],
                "checkpoint":
                    "technology/component_models/two_stage_output_stage_fullR.pt",
                "model_kind": "binary_feasibility_classifier",
                "mlp_features": [
                    "vout_v",
                    "vy_v",
                    "vbias_v",
                    "stage_ratio",
                ],
                "interface_inputs": ["first_second_stage_cut"],
                "interface_outputs": [],
                "local_search_coordinates": [
                    {
                        "name": "vout_v",
                        "kind": "voltage",
                        "grid": {
                            "minimum": 0.5,
                            "maximum": 1.6,
                            "count": 12,
                            "spacing": "linear",
                        },
                    }
                ],
                "exact_realizer": {
                    "driver": "witness_plan_builder",
                    "module":
                        "tools/validation/run_two_stage_independent_tables_v2.py",
                    "builder_function": "build_b_plan",
                    "base_plan":
                        "examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml",
                    "witnesses_per_state": 3,
                },
            },
        ],
        "interfaces": [
            {
                "id": "first_second_stage_cut",
                "between": ["input_bias_network", "output_stage"],
                "coordinates": [
                    {
                        "name": "vy_v",
                        "kind": "voltage",
                        "physical_nodes": ["n2"],
                        "relation": "shared_equal_coordinate",
                        "grid": {
                            "minimum": 0.15,
                            "maximum": 1.65,
                            "count": 61,
                            "spacing": "linear",
                        },
                    },
                    {
                        "name": "vbias_v",
                        "kind": "voltage",
                        "physical_nodes": ["vbias"],
                        "relation": "shared_equal_coordinate",
                        "grid": {
                            "minimum": 0.55,
                            "maximum": 1.05,
                            "count": 9,
                            "spacing": "linear",
                        },
                    },
                ],
                "propagated_variables": [
                    {
                        "name": "stage_ratio",
                        "source_component": "input_bias_network",
                        "destination_component": "output_stage",
                        "semantics": "exact_value_after_realization",
                        "training_domain": {
                            "minimum": 0.04,
                            "maximum": 200.0,
                        },
                    }
                ],
            }
        ],
        "final_witness": {
            "semantics": "complete_spice_realizable_assignment",
            "deduplicate_on": [
                "w_m1_um", "w_m2_um", "w_m3_um", "w_m4_um",
                "w_m5_um", "w_m6_um", "w_m7_um",
                "vbias_v", "vout_v",
            ],
            "canonical_fields": {
                "w_m1_um": "A_w_m1_um",
                "w_m2_um": "A_w_m1_um",
                "w_m3_um": "A_w_m3_um",
                "w_m4_um": "A_w_m3_um",
                "w_m5_um": "A_w_m5_um",
                "w_m6_um": "B_w_m6_um",
                "w_m7_um": "B_w_m7_um",

                "i_m1_a": "A_id_m1_a",
                "i_m2_a": "A_id_m2_a",
                "i_m3_a": "A_id_m3_a",
                "i_m4_a": "A_id_m4_a",
                "i_m5_a": "A_id_m5_a",
                "i_m6_a": "B_id_m6_a",
                "i_m7_a": "B_id_m7_a",

                "vtail_v": "A_vtail_v",
                "n1_v": "A_vx_v",
                "n2_v": "A_vy_v",
                "vbias_v": "A_vbias_v",
                "vout_v": "B_vout_v",
                "stage_ratio": "B_stage_ratio",

                "sat_M1_headroom_v": "A_sat_M1_headroom_v",
                "sat_M2_headroom_v": "A_sat_M2_headroom_v",
                "sat_M3_headroom_v": "A_sat_M3_headroom_v",
                "sat_M4_headroom_v": "A_sat_M4_headroom_v",
                "sat_M5_headroom_v": "A_sat_M5_headroom_v",
                "sat_M6_headroom_v": "B_sat_M6_headroom_v",
                "sat_M7_headroom_v": "B_sat_M7_headroom_v",
            },
        },
    }

    args.intent.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    print("updated:", args.intent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Add the first hierarchical-feasibility declaration to the folded-cascode
design_intent.yaml.  This is declarative Step-4 data; the generic compiler
contains no folded-cascode-specific logic.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intent", required=True, type=Path)
    args = ap.parse_args()

    with args.intent.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    data["hierarchical_feasibility"] = {
        "strategy": "hierarchical_component_mlp_discrete_interface",
        "realization_method": "device_mlp_realize_surviving_interface_cells",
        "final_validation": ["device_mlp", "ngspice_dc"],

        "derived_relations": [
            {"variable": "i_m1_a", "expression": "0.5 * i_m3_a"},
            {"variable": "i_m2_a", "expression": "0.5 * i_m3_a"},
            {"variable": "i_m4_a", "expression": "1.5 * i_m3_a"},
            {"variable": "i_m5_a", "expression": "1.5 * i_m3_a"},
            {"variable": "i_m6_a", "expression": "i_m4_a - i_m1_a"},
            {"variable": "i_m7_a", "expression": "i_m5_a - i_m2_a"},
            {"variable": "i_m8_a", "expression": "i_m6_a"},
            {"variable": "i_m9_a", "expression": "i_m7_a"},
            {"variable": "i_m10_a", "expression": "i_m8_a"},
            {"variable": "i_m11_a", "expression": "i_m9_a"},
        ],

        "components": [
            {
                "id": "input_tail_network",
                "source_group": "input_tail_network",
                "mlp_inputs": ["w_m1_um", "i_m3_a", "vp_v"],
                "interface_inputs": [],
                "interface_outputs": ["upper_folded_cut"],
                "checkpoint":
                    "technology/component_models/folded_input_tail_network.pt",
            },
            {
                "id": "upper_folded_network",
                "source_group": "upper_folded_network",
                "mlp_inputs": ["i_m3_a", "vp_v", "vx_v"],
                "interface_inputs": ["upper_folded_cut"],
                "interface_outputs": ["folded_lower_cut"],
                "checkpoint":
                    "technology/component_models/folded_upper_folded_network.pt",
            },
            {
                "id": "lower_output_network",
                "source_group": "lower_output_network",
                "mlp_inputs": ["i_m3_a", "vx_v"],
                "interface_inputs": ["folded_lower_cut"],
                "interface_outputs": [],
                "checkpoint":
                    "technology/component_models/folded_lower_output_network.pt",
            },
        ],

        "interfaces": [
            {
                "id": "upper_folded_cut",
                "between": ["input_tail_network", "upper_folded_network"],
                "coordinates": [
                    {
                        "name": "vp_v",
                        "kind": "voltage",
                        "physical_nodes": ["psrc_left", "psrc_right"],
                        "relation": "equal_under_balanced_dc",
                        "grid": {
                            "minimum": 0.001,
                            "maximum": 1.799,
                            "count": 31,
                            "spacing": "linear",
                        },
                    }
                ],
            },
            {
                "id": "folded_lower_cut",
                "between": ["upper_folded_network", "lower_output_network"],
                "coordinates": [
                    {
                        "name": "vx_v",
                        "kind": "voltage",
                        "physical_nodes": ["x", "vout"],
                        "relation": "equal_under_balanced_dc",
                        "grid": {
                            "minimum": 0.05,
                            "maximum": 1.75,
                            "count": 21,
                            "spacing": "linear",
                        },
                    }
                ],
            },
        ],
    }

    with args.intent.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)

    print("updated:", args.intent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

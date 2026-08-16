#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import yaml

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intent", required=True, type=Path)
    args = ap.parse_args()
    data = yaml.safe_load(args.intent.read_text())

    data["hierarchical_feasibility"] = {
        "strategy": "hierarchical_component_mlp_discrete_interface",
        "realization_method": "device_mlp_realize_surviving_interface_cells",
        "final_validation": ["device_mlp", "ngspice_dc"],
        "derived_relations": [
            {"variable": "i_m1_a", "expression": "0.5 * i_m5_a"},
            {"variable": "i_m2_a", "expression": "0.5 * i_m5_a"},
            {"variable": "i_m3_a", "expression": "i_m1_a"},
            {"variable": "i_m4_a", "expression": "i_m2_a"},
            {"variable": "stage_ratio", "expression": "2.0 * w_m3_um / w_m5_um",
             "meaning": "w_m6_um / w_m7_um"},
        ],
        "components": [
            {
                "id": "input_bias_network",
                "source_group": "input_bias_network",
                "mlp_inputs": ["w_m1_um","i_m5_a","vy_v","vbias_v","stage_ratio"],
                "interface_inputs": [],
                "interface_outputs": ["first_second_stage_cut"],
                "checkpoint": "technology/component_models/two_stage_input_bias_network.pt",
            },
            {
                "id": "output_stage",
                "source_group": "output_stage",
                "mlp_inputs": ["i_m5_a","vout_v","vy_v","vbias_v","stage_ratio"],
                "interface_inputs": ["first_second_stage_cut"],
                "interface_outputs": [],
                "checkpoint": "technology/component_models/two_stage_output_stage.pt",
            },
        ],
        "interfaces": [
            {
                "id": "first_second_stage_cut",
                "between": ["input_bias_network","output_stage"],
                "coordinates": [
                    {"name":"vy_v","kind":"voltage","physical_nodes":["n2"],
                     "relation":"shared_equal_coordinate",
                     "grid":{"minimum":0.15,"maximum":1.65,"count":11,"spacing":"linear"}},
                    {"name":"vbias_v","kind":"voltage","physical_nodes":["vbias"],
                     "relation":"shared_equal_coordinate",
                     "grid":{"minimum":0.55,"maximum":1.05,"count":9,"spacing":"linear"}},
                    {"name":"stage_ratio","kind":"dimensionless","physical_nodes":[],
                     "relation":"shared_equal_coordinate",
                     "grid":{"minimum":0.1,"maximum":20.0,"count":9,"spacing":"log"}},
                ],
            }
        ],
    }

    args.intent.write_text(yaml.safe_dump(data, sort_keys=False))
    print("updated:", args.intent)

if __name__ == "__main__":
    raise SystemExit(main())

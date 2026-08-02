#!/usr/bin/env python3
"""Build the two-stage topology contract for the generic solver.

Only this contract is topology-specific. The solver remains generic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--intent",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/inputs/design_intent.yaml"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/"
            "generic_assignment_contract.json"
        ),
    )
    args = parser.parse_args()

    intent = yaml.safe_load(args.intent.read_text(encoding="utf-8"))
    width_policy = (
        intent["synthesis_parameterization"]
        ["dependent_width_realization"]
    )

    constraints = [
        {"id": "i1", "kind": "expression", "target": "i_m1_a", "expression": "i_m5_a / 2"},
        {"id": "i2", "kind": "equal", "left": "i_m2_a", "right": "i_m1_a"},
        {"id": "i3", "kind": "equal", "left": "i_m3_a", "right": "i_m1_a"},
        {"id": "i4", "kind": "equal", "left": "i_m4_a", "right": "i_m2_a", "absolute_tolerance": 1e-6, "relative_tolerance": 0.1},

        {"id": "w1", "kind": "width_from_row", "device": "M1", "current": "i_m1_a", "width": "w_m1_um"},
        {
            "id": "w2_realization",
            "kind": "copy_width_realization",
            "source_device": "M1",
            "target_device": "M2",
            "source_width": "w_m1_um",
            "target_width": "w_m2_um",
        },
        {"id": "w3", "kind": "width_from_row", "device": "M3", "current": "i_m3_a", "width": "w_m3_um"},
        {
            "id": "w4_realization",
            "kind": "copy_width_realization",
            "source_device": "M3",
            "target_device": "M4",
            "source_width": "w_m3_um",
            "target_width": "w_m4_um",
        },
        {"id": "w5", "kind": "width_from_row", "device": "M5", "current": "i_m5_a", "width": "w_m5_um"},

        {
            "id": "m1_m2_match",
            "kind": "matched_operating_point",
            "left_device": "M1",
            "right_device": "M2",
            "quantities": ["vgs_v", "vbs_v", "density_a_per_um"],
            "absolute_tolerance": 1e-12,
            "relative_tolerance": 1e-10,
        },
        {"id": "m3_diode", "kind": "diode_connected", "device": "M3", "absolute_tolerance": 0.025},

        {"id": "m1_gate", "kind": "terminal_node", "device": "M1", "source_node": "vtail_v", "target_node": "vin_cm_v", "terminal": "gate", "absolute_tolerance": 0.025},
        {"id": "m1_drain", "kind": "terminal_node", "device": "M1", "source_node": "vtail_v", "target_node": "n1_v", "terminal": "drain", "absolute_tolerance": 0.025},
        {"id": "m2_gate", "kind": "terminal_node", "device": "M2", "source_node": "vtail_v", "target_node": "vin_cm_v", "terminal": "gate", "absolute_tolerance": 0.025},
        {"id": "m2_drain", "kind": "terminal_node", "device": "M2", "source_node": "vtail_v", "target_node": "n2_v", "terminal": "drain", "absolute_tolerance": 0.025},

        {"id": "m5_drain", "kind": "terminal_node", "device": "M5", "source_node": "vss_v", "target_node": "vtail_v", "terminal": "drain", "absolute_tolerance": 0.025},
        {"id": "m5_gate", "kind": "terminal_node", "device": "M5", "source_node": "vss_v", "target_node": "vbias_v", "terminal": "gate", "absolute_tolerance": 0.025},

        {"id": "m3_gate", "kind": "terminal_node", "device": "M3", "source_node": "vdd_v", "target_node": "n1_v", "terminal": "gate", "absolute_tolerance": 0.025},
        {"id": "m3_drain", "kind": "terminal_node", "device": "M3", "source_node": "vdd_v", "target_node": "n1_v", "terminal": "drain", "absolute_tolerance": 0.025},
        {"id": "m4_gate", "kind": "terminal_node", "device": "M4", "source_node": "vdd_v", "target_node": "n1_v", "terminal": "gate", "absolute_tolerance": 0.025},
        {"id": "m4_drain", "kind": "terminal_node", "device": "M4", "source_node": "vdd_v", "target_node": "n2_v", "terminal": "drain", "absolute_tolerance": 0.025},

        {"id": "m7_gate", "kind": "terminal_node", "device": "M7", "source_node": "vss_v", "target_node": "vbias_v", "terminal": "gate", "absolute_tolerance": 0.025},
        {"id": "m7_drain", "kind": "terminal_node", "device": "M7", "source_node": "vss_v", "target_node": "vout_v", "terminal": "drain", "absolute_tolerance": 0.025},

        {"id": "vds6", "kind": "expression", "target": "vds_m6_v", "expression": "vdd_v - vout_v"},
        {
            "id": "d7",
            "kind": "row_density",
            "device": "M7",
            "target": "density_m7_a_per_um",
        },
        {
            "id": "m6_density",
            "kind": "coupled_density",
            "target_device": "M6",
            "fixed_vds_variable": "vds_m6_v",
            "density_expression": "density_m7_a_per_um * w_m5_um / (2 * w_m4_um)",
            "vds_tolerance": 1e-9,
        },
        {"id": "m6_gate", "kind": "terminal_node", "device": "M6", "source_node": "vdd_v", "target_node": "n2_v", "terminal": "gate", "absolute_tolerance": 0.025},
        {"id": "m6_drain", "kind": "terminal_node", "device": "M6", "source_node": "vdd_v", "target_node": "vout_v", "terminal": "drain", "absolute_tolerance": 0.025},

        {
            "id": "common_output_current",
            "kind": "common_current_interval",
            "left_device": "M6",
            "right_device": "M7",
            "output_current": "i_output_a",
            "selection": "minimum",
        },
        {"id": "i6", "kind": "equal", "left": "i_m6_a", "right": "i_output_a"},
        {"id": "i7", "kind": "equal", "left": "i_m7_a", "right": "i_output_a"},
        {"id": "w6", "kind": "width_from_density", "device": "M6", "current": "i_m6_a", "width": "w_m6_um"},
        {"id": "w7", "kind": "width_from_density", "device": "M7", "current": "i_m7_a", "width": "w_m7_um"},

        {"id": "vtail_bounds", "kind": "bounds", "variable": "vtail_v", "minimum": 0.0, "maximum": 0.9},
        {"id": "n1_bounds", "kind": "bounds", "variable": "n1_v", "minimum": 0.0, "maximum": 1.8},
        {"id": "n2_bounds", "kind": "bounds", "variable": "n2_v", "minimum": 0.0, "maximum": 1.8},
        {"id": "vout_bounds", "kind": "bounds", "variable": "vout_v", "minimum": 0.5, "maximum": 1.6},
    ]

    for device in ("M1", "M2", "M3", "M4", "M5", "M6", "M7"):
        constraints.append(
            {
                "id": f"{device.lower()}_sat",
                "kind": "saturation_margin",
                "device": device,
                "minimum_margin_v": 0.0,
            }
        )

    required = [
        *(f"i_m{index}_a" for index in range(1, 8)),
        *(f"w_m{index}_um" for index in range(1, 8)),
        "vtail_v", "n1_v", "n2_v", "vbias_v", "vout_v",
        *(f"nf_m{index}" for index in range(1, 8)),
        *(f"w_finger_m{index}_um" for index in range(1, 8)),
    ]

    contract = {
        "artifact": "openams.generic_assignment_contract",
        "schema_version": 2,
        "devices": ["M1", "M2", "M3", "M4", "M5", "M7", "M6"],
        "row_selected_devices": ["M1", "M2", "M5", "M3", "M4", "M7"],
        "copied_devices": [],
        "interpolated_devices": ["M6"],
        "independent_variables": ["i_m5_a", "w_m1_um", "vout_v"],
        "constants": {
            "vdd_v": 1.8,
            "vss_v": 0.0,
            "vin_cm_v": 0.9,
        },
        "width_policy": width_policy,
        "required_complete_quantities": required,
        "constraints": constraints,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[PASS] wrote {args.output}")
    print(f"[INFO] constraints={len(constraints)}")
    print(f"[INFO] required_quantities={len(required)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

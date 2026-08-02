from __future__ import annotations

import csv
import json
from pathlib import Path

from openams.synthesis.independent_domains import build_independent_domains


def _table(path: Path) -> None:
    fields = [
        "polarity", "model", "length_um", "width_um",
        "vgs_abs_v", "vds_abs_v", "vbs_abs_v",
        "id_abs_a", "saturated",
    ]
    rows = [
        ["nmos", "nmos_model", 0.5, 1.0, 0.7, 0.5, 0.0, 20e-6, True],
        ["nmos", "nmos_model", 0.5, 100.0, 0.8, 1.5, 0.0, 40e-6, True],
        ["pmos", "pmos_model", 0.5, 1.0, 0.7, 0.3, 0.0, 20e-6, True],
        ["pmos", "pmos_model", 0.5, 100.0, 0.8, 1.2, 0.0, 40e-6, True],
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)


def _model(table: Path) -> dict:
    return {
        "artifact": "openams.compiled_circuit_model",
        "circuit_name": "two_stage_opamp",
        "technology": {
            "source_path": str(table),
            "technology_name": "test",
        },
        "project_inputs": {
            "specifications": {
                "dc_validity": {
                    "output_voltage": {"min": 0.2, "max": 1.6}
                }
            },
            "design_rules": {
                "operating_conditions": {"vdd_v": 1.8, "vss_v": 0.0},
                "device_constraints": {
                    "all_mos": {
                        "required_region": "saturation",
                        "length_um": 0.5,
                        "width_min_um": 0.42,
                        "width_max_um": 100.0,
                        "body_voltage_abs_max_v": 1e-9,
                    }
                },
            },
        },
        "topology": {
            "devices": [
                {
                    "name": "XM1", "kind": "mos", "model": "nmos_model",
                    "terminals": {
                        "drain": "n1", "source": "ntail",
                        "gate": "inp", "bulk": "vss",
                    },
                },
                {
                    "name": "XM5", "kind": "mos", "model": "nmos_model",
                    "terminals": {
                        "drain": "ntail", "source": "vss",
                        "gate": "vbias", "bulk": "vss",
                    },
                },
                {
                    "name": "XM6", "kind": "mos", "model": "pmos_model",
                    "terminals": {
                        "drain": "out", "source": "vdd",
                        "gate": "n2", "bulk": "vdd",
                    },
                },
                {
                    "name": "XM7", "kind": "mos", "model": "nmos_model",
                    "terminals": {
                        "drain": "out", "source": "vss",
                        "gate": "vbias", "bulk": "vss",
                    },
                },
            ]
        },
        "synthesis_interface": {
            "independent_variables": [
                {
                    "id": "i_m5_a",
                    "original": {
                        "kind": "current",
                        "minimum": 10e-6,
                        "maximum": 100e-6,
                    },
                },
                {
                    "id": "w_m1_um",
                    "original": {
                        "kind": "total_width",
                        "minimum": 1.0,
                        "maximum": 300.0,
                        "finger_realization": {
                            "finger_width_min_um": 0.42,
                            "finger_width_max_um": 100.0,
                            "scaling_model": "linear_current_scaling",
                        },
                    },
                },
                {
                    "id": "vout_v",
                    "original": {
                        "kind": "node_voltage",
                        "minimum": 0.5,
                        "maximum": 1.8,
                    },
                },
            ]
        },
    }


def test_total_width_and_continuous_vout(tmp_path: Path) -> None:
    table = tmp_path / "table.csv"
    _table(table)
    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps(_model(table)), encoding="utf-8")

    artifact = build_independent_domains(model_path)
    width = artifact["domains"]["w_m1_um"]
    vout = artifact["domains"]["vout_v"]

    assert width["domain_type"] == "technology_realizable_continuous_total_width"
    assert width["technology_minimum"] == 1.0
    assert width["technology_maximum"] == 300.0
    assert width["nf_max"] >= 3
    assert vout["domain_type"] == "technology_supported_continuous_interval"
    assert vout["technology_minimum"] == 0.6
    assert vout["technology_maximum"] == 1.5

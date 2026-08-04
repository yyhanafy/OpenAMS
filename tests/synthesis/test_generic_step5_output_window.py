from __future__ import annotations

from openams.synthesis.generic_complete_step5 import _intersect_output_device_windows


def _model():
    return {
        "project_inputs": {"design_rules": {"technology_intersection": {"node_voltage_tolerance_v": 0.025}}},
        "topology": {
            "ports": ["inp", "inn", "out", "vdd", "vss"],
            "devices": [
                {
                    "kind": "mos",
                    "name": "XM7",
                    "model": "sky130_fd_pr__pfet_01v8",
                    "terminals": {"drain": "out", "gate": "vpb2", "source": "psrc", "bulk": "vdd"},
                },
                {
                    "kind": "mos",
                    "name": "XM9",
                    "model": "sky130_fd_pr__nfet_01v8",
                    "terminals": {"drain": "out", "gate": "vnb2", "source": "nlow", "bulk": "vss"},
                },
            ],
        },
    }


def test_output_windows_intersect():
    values = {"vout_min_v": 0.2, "vout_max_v": 1.6}
    nodes = {"psrc": 1.5, "nlow": 0.3}
    provenance = {
        "M7": {"minimum_saturated_vds_v": 0.2, "maximum_characterized_vds_v": 0.8},
        "M9": {"minimum_saturated_vds_v": 0.15, "maximum_characterized_vds_v": 0.7},
    }

    assert _intersect_output_device_windows(_model(), values, nodes, provenance)
    assert values["vout_min_v"] == 0.7
    assert values["vout_max_v"] == 1.0


def test_empty_output_window_is_rejected():
    values = {"vout_min_v": 0.2, "vout_max_v": 1.6}
    nodes = {"psrc": 0.7, "nlow": 0.6}
    provenance = {
        "M7": {"minimum_saturated_vds_v": 0.2, "maximum_characterized_vds_v": 0.3},
        "M9": {"minimum_saturated_vds_v": 0.2, "maximum_characterized_vds_v": 0.3},
    }

    assert not _intersect_output_device_windows(_model(), values, nodes, provenance)

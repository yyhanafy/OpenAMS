from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path("src/openams/synthesis/generic_complete_step5.py")


def load_module():
    module_name = "generic_complete_step5_under_test"
    sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    return module


def test_final_validation_helper_is_exported() -> None:
    module = load_module()
    assert hasattr(module, "_final_selected_device_failures")


def test_unresolved_drain_is_deferred_not_failed() -> None:
    module = load_module()

    model = {
        "project_inputs": {
            "design_rules": {
                "technology_intersection": {
                    "node_voltage_tolerance_v": 0.025,
                }
            }
        },
        "topology": {
            "devices": [
                {
                    "kind": "mos",
                    "name": "XM9",
                    "model": "sky130_fd_pr__nfet_01v8",
                    "terminals": {
                        "drain": "vout",
                        "gate": "vnb2",
                        "source": "nlow",
                        "bulk": "vss",
                    },
                }
            ]
        },
    }

    nodes = {
        "vnb2": 0.9,
        "nlow": 0.2,
        "vss": 0.0,
    }

    provenance = {
        "M9": {
            "vgs_v": 0.7,
            "vbs_v": 0.2,
            "minimum_saturated_vds_v": 0.15,
            "maximum_characterized_vds_v": 0.8,
            "vdsat_v": 0.1,
        }
    }

    assert module._final_selected_device_failures(
        model, nodes, provenance
    ) == []


def test_known_vds_below_min_is_rejected() -> None:
    module = load_module()

    model = {
        "project_inputs": {
            "design_rules": {
                "technology_intersection": {
                    "node_voltage_tolerance_v": 0.025,
                }
            }
        },
        "topology": {
            "devices": [
                {
                    "kind": "mos",
                    "name": "XM4",
                    "model": "sky130_fd_pr__pfet_01v8",
                    "terminals": {
                        "drain": "psrc",
                        "gate": "vpb1",
                        "source": "vdd",
                        "bulk": "vdd",
                    },
                }
            ]
        },
    }

    nodes = {
        "vdd": 1.8,
        "vpb1": 0.0,
        "psrc": 1.525,
    }

    provenance = {
        "M4": {
            "vgs_v": 1.8,
            "vbs_v": 0.0,
            "minimum_saturated_vds_v": 0.8,
            "maximum_characterized_vds_v": 1.8,
            "vdsat_v": 0.748,
        }
    }

    failures = module._final_selected_device_failures(
        model, nodes, provenance
    )
    assert failures == ["FINAL_VDS_BELOW_MIN:M4"]


def test_known_valid_device_passes() -> None:
    module = load_module()

    model = {
        "project_inputs": {
            "design_rules": {
                "technology_intersection": {
                    "node_voltage_tolerance_v": 0.025,
                }
            }
        },
        "topology": {
            "devices": [
                {
                    "kind": "mos",
                    "name": "XM4",
                    "model": "sky130_fd_pr__pfet_01v8",
                    "terminals": {
                        "drain": "psrc",
                        "gate": "vpb1",
                        "source": "vdd",
                        "bulk": "vdd",
                    },
                }
            ]
        },
    }

    nodes = {
        "vdd": 1.8,
        "vpb1": 0.7,
        "psrc": 1.5,
    }

    provenance = {
        "M4": {
            "vgs_v": 1.1,
            "vbs_v": 0.0,
            "minimum_saturated_vds_v": 0.19,
            "maximum_characterized_vds_v": 0.6,
            "vdsat_v": 0.139,
        }
    }

    assert module._final_selected_device_failures(
        model, nodes, provenance
    ) == []

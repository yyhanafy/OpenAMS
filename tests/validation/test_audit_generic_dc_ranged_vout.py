from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/validation/audit_generic_dc_assignments.py")


def load_module():
    name = "audit_generic_dc_assignments_under_test"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _model():
    return {
        "topology": {
            "devices": [
                {
                    "kind": "mos",
                    "name": "XM7",
                    "model": "sky130_fd_pr__pfet_01v8",
                    "terminals": {
                        "drain": "out",
                        "gate": "vpb2",
                        "source": "psrc",
                        "bulk": "vdd",
                    },
                },
                {
                    "kind": "mos",
                    "name": "XM9",
                    "model": "sky130_fd_pr__nfet_01v8",
                    "terminals": {
                        "drain": "out",
                        "gate": "vnb2",
                        "source": "nlow",
                        "bulk": "vss",
                    },
                },
            ]
        }
    }


def test_ranged_vout_devices_pass() -> None:
    module = load_module()
    assignment = {
        "assignment_id": "a0",
        "vout_min_v": 0.7,
        "vout_max_v": 1.0,
        "device_technology_provenance": {
            "M7": {
                "vgs_v": 1.0,
                "vbs_v": 0.3,
                "minimum_saturated_vds_v": 0.2,
                "maximum_characterized_vds_v": 0.8,
                "vdsat_v": 0.15,
            },
            "M9": {
                "vgs_v": 0.7,
                "vbs_v": 0.3,
                "minimum_saturated_vds_v": 0.15,
                "maximum_characterized_vds_v": 0.7,
                "vdsat_v": 0.10,
            },
        },
    }
    nodes = {
        "psrc": 1.5,
        "vpb2": 0.5,
        "vdd": 1.8,
        "nlow": 0.3,
        "vnb2": 1.0,
        "vss": 0.0,
    }

    rows = module.audit_rows(_model(), assignment, nodes, 0.025)
    assert all(row["status"] == "PASS" for row in rows)
    assert all("ranged_vout" in row["passed_checks"] for row in rows)


def test_ranged_vout_below_min_fails() -> None:
    module = load_module()
    assignment = {
        "assignment_id": "a1",
        "vout_min_v": 0.35,
        "vout_max_v": 0.5,
        "device_technology_provenance": {
            "M9": {
                "vgs_v": 0.7,
                "vbs_v": 0.3,
                "minimum_saturated_vds_v": 0.2,
                "maximum_characterized_vds_v": 0.7,
                "vdsat_v": 0.15,
            },
        },
    }
    model = {
        "topology": {
            "devices": [
                {
                    "kind": "mos",
                    "name": "XM9",
                    "model": "sky130_fd_pr__nfet_01v8",
                    "terminals": {
                        "drain": "out",
                        "gate": "vnb2",
                        "source": "nlow",
                        "bulk": "vss",
                    },
                }
            ]
        }
    }
    nodes = {
        "nlow": 0.3,
        "vnb2": 1.0,
        "vss": 0.0,
    }

    row = module.audit_rows(model, assignment, nodes, 0.025)[0]
    assert row["status"] == "INCOMPLETE_OR_FAIL"
    assert "RANGED_VDS_BELOW_MIN" in row["failures"]

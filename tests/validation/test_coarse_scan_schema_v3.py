from __future__ import annotations

import importlib.util
from pathlib import Path


def load_runner_module():
    path = Path(__file__).resolve().parents[2] / "tools/validation/run_coarse_independent_ac_scan.py"
    spec = importlib.util.spec_from_file_location("run_coarse_scan", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_v3_contains_complete_device_and_validation_fields() -> None:
    module = load_runner_module()
    fields = set(module.make_fieldnames())

    required_global = {
        "schema_version", "grid_index", "assignment_id", "status",
        "failure_stage", "failure_type", "failure",
        "i_m5_a", "w_m1_um", "vout_v", "vtail_v", "n1_v", "n2_v", "vbias_v",
        "gain_est_v_v", "gain_est_db", "ugb_est_hz",
        "phase_at_ugb_unwrapped_est_deg", "phase_at_ugb_est_deg", "phase_margin_est_deg",
        "supply_current_est_a", "power_est_w",
        "max_kcl_residual_a", "max_device_current_residual_a",
        "max_device_current_relative_residual",
        "gain_spec_pass", "ugb_spec_pass", "phase_margin_spec_pass",
        "power_spec_pass", "overall_spec_pass",
    }
    assert required_global <= fields

    for index in range(1, 8):
        prefix = f"m{index}"
        required_device = {
            f"i_m{index}_a", f"w_m{index}_um",
            f"{prefix}_polarity", f"{prefix}_length_um",
            f"{prefix}_vgs_abs_v", f"{prefix}_vds_abs_v", f"{prefix}_vbs_abs_v",
            f"{prefix}_vd_v", f"{prefix}_vg_v", f"{prefix}_vs_v", f"{prefix}_vb_v",
            f"{prefix}_vgs_signed_v", f"{prefix}_vds_signed_v", f"{prefix}_vbs_signed_v",
            f"{prefix}_id_abs_a", f"{prefix}_vth_abs_v", f"{prefix}_vdsat_abs_v",
            f"{prefix}_vov_abs_v", f"{prefix}_gm_s", f"{prefix}_gds_s",
            f"{prefix}_gm_over_id_1_v", f"{prefix}_ro_ohm",
            f"{prefix}_cgs_f", f"{prefix}_cgd_f", f"{prefix}_cdb_f", f"{prefix}_csb_f",
            f"{prefix}_target_current_a", f"{prefix}_current_residual_a",
            f"{prefix}_current_relative_residual", f"{prefix}_saturation_margin_v",
            f"{prefix}_saturated", f"{prefix}_in_domain",
        }
        assert required_device <= fields

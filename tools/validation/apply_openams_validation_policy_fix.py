#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path.cwd()
DC = ROOT / "tools/validation/run_ngspice_dc_validation.py"
AC = ROOT / "tools/validation/run_ngspice_ac_validation.py"


def backup(path: Path) -> Path:
    target = path.with_suffix(path.suffix + ".before_policy_fix")
    if not target.exists():
        shutil.copy2(path, target)
    return target


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Could not patch {label}; matches={count}")
    return updated


def patch_dc() -> None:
    if not DC.is_file():
        raise FileNotFoundError(DC)

    backup(DC)
    text = DC.read_text()

    text = replace_once(
        text,
        r'''    dc_physical_valid = \(
        extraction_complete
        and all_internal_nodes_match
        and all_currents_match
        and all_devices_saturated
        and vout_within_window
    \)
    exact_realization_pass = dc_physical_valid and vout_target_match
    proceed_to_ac = dc_physical_valid

    if not extraction_complete:
        classification = "EXTRACTION_OR_CONVERGENCE_FAILURE"
    elif not dc_physical_valid:
        classification = "PHYSICALLY_INVALID_OR_OUTSIDE_WINDOW"
    elif vout_target_match:
        classification = "PASS_PHYSICAL_AND_TARGET_MATCH"
    else:
        classification = "PASS_PHYSICAL_WITH_VOUT_WARNING"
''',
        '''    # Physical validity is decided only from the actual ngspice circuit.
    # Model-to-ngspice discrepancies are diagnostics, not validity gates.
    dc_physical_valid = (
        extraction_complete
        and all_devices_saturated
        and vout_within_window
    )
    exact_realization_pass = (
        dc_physical_valid
        and vout_target_match
        and all_internal_nodes_match
        and all_currents_match
    )
    proceed_to_ac = dc_physical_valid

    model_accuracy_warnings = []
    if dc_physical_valid and not all_internal_nodes_match:
        model_accuracy_warnings.append("INTERNAL_NODE_MODEL_WARNING")
    if dc_physical_valid and not all_currents_match:
        model_accuracy_warnings.append("CURRENT_MODEL_WARNING")
    if dc_physical_valid and not vout_target_match:
        model_accuracy_warnings.append("VOUT_TARGET_MODEL_WARNING")

    if not extraction_complete:
        classification = "EXTRACTION_OR_CONVERGENCE_FAILURE"
    elif not all_devices_saturated:
        classification = "PHYSICALLY_INVALID_DEVICE_REGION"
    elif not vout_within_window:
        classification = "PHYSICALLY_INVALID_VOUT_WINDOW"
    elif model_accuracy_warnings:
        classification = "PASS_PHYSICAL_WITH_MODEL_WARNINGS"
    else:
        classification = "PASS_PHYSICAL_AND_MODEL_MATCH"
''',
        "physical validity block",
    )

    text = replace_once(
        text,
        r'''        "vout_target_warning": dc_physical_valid and not vout_target_match,
        "dc_physical_valid": dc_physical_valid,''',
        '''        "vout_target_warning": dc_physical_valid and not vout_target_match,
        "internal_node_model_warning": dc_physical_valid and not all_internal_nodes_match,
        "current_model_warning": dc_physical_valid and not all_currents_match,
        "model_accuracy_warnings": model_accuracy_warnings,
        "dc_physical_valid": dc_physical_valid,''',
        "result warnings",
    )

    text = replace_once(
        text,
        r'''        "vout_target_warning": result\["vout_target_warning"\],
        "runtime_s": result\["runtime_s"\],''',
        '''        "vout_target_warning": result["vout_target_warning"],
        "internal_node_model_warning": result["internal_node_model_warning"],
        "current_model_warning": result["current_model_warning"],
        "model_accuracy_warnings": ";".join(result["model_accuracy_warnings"]),
        "runtime_s": result["runtime_s"],''',
        "flatten warnings",
    )

    text = replace_once(
        text,
        r'''    warnings = sum\(bool\(row\["vout_target_warning"\]\) for row in aggregate\)
    proceed = sum\(bool\(row\["proceed_to_ac"\]\) for row in aggregate\)''',
        '''    vout_warnings = sum(bool(row["vout_target_warning"]) for row in aggregate)
    node_warnings = sum(bool(row["internal_node_model_warning"]) for row in aggregate)
    current_warnings = sum(bool(row["current_model_warning"]) for row in aggregate)
    proceed = sum(bool(row["proceed_to_ac"]) for row in aggregate)''',
        "warning counters",
    )

    text = replace_once(
        text,
        r'''        "vout_target_warnings": warnings,
        "proceed_to_ac": proceed,''',
        '''        "vout_target_warnings": vout_warnings,
        "internal_node_model_warnings": node_warnings,
        "current_model_warnings": current_warnings,
        "proceed_to_ac": proceed,''',
        "summary warnings",
    )

    text = replace_once(
        text,
        r'''    print\(f"Vout warnings:      \{warnings\}"\)
    print\(f"proceed to AC:      \{proceed\}"\)''',
        '''    print(f"Vout warnings:      {vout_warnings}")
    print(f"node warnings:      {node_warnings}")
    print(f"current warnings:   {current_warnings}")
    print(f"proceed to AC:      {proceed}")''',
        "summary printing",
    )

    text = text.replace(
        "===== OPENAMS NGSPICE DC VALIDATION V2 =====",
        "===== OPENAMS NGSPICE DC VALIDATION V3 =====",
    )
    DC.write_text(text)


def verify_ac() -> None:
    if not AC.is_file():
        raise FileNotFoundError(AC)

    text = AC.read_text()
    required = [
        "--run-ngspice",
        "--require-fresh-ac",
        "absolute_phase_unwrapped_deg",
        "phase_margin_deg = 180.0 + phase_at_ugb_unwrapped_deg",
        "openams_ac_newer_than_deck",
        "deck_sha256",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError("AC validator missing required signed/provenance logic: " + ", ".join(missing))


def main() -> int:
    patch_dc()
    verify_ac()
    print("[PASS] patched:", DC)
    print("[PASS] verified:", AC)
    print("[INFO] backup:", DC.with_suffix(DC.suffix + ".before_policy_fix"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

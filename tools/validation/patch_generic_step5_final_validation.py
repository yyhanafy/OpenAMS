#!/usr/bin/env python3
"""Patch generic Step 5 so invalid completed branches do not consume the solution cap."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


target = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "src/openams/synthesis/generic_complete_step5.py"
)
text = target.read_text(encoding="utf-8")

helper = r'''

def _final_selected_device_failures(
    model: Mapping[str, Any],
    nodes: Mapping[str, float],
    provenance: Mapping[str, Any],
) -> list[str]:
    """Globally revalidate selected MOS devices at a completed search branch.

    A device with an unresolved drain, normally because it connects to a
    ranged VOUT node, remains deferred rather than being rejected here.
    """

    devices = _device_map(model)
    intersection = (
        model["project_inputs"]["design_rules"]
        .get("technology_intersection", {})
    )
    tolerance = float(
        intersection.get("node_voltage_tolerance_v", 0.025)
    )
    failures: list[str] = []

    for member, item in provenance.items():
        device = devices.get(str(member).upper())
        if device is None:
            failures.append(f"FINAL_UNKNOWN_DEVICE:{member}")
            continue

        polarity = _polarity(str(device["model"]))
        terminals = {
            key: str(value).lower()
            for key, value in device.get("terminals", {}).items()
        }

        vd = nodes.get(terminals.get("drain", ""))
        vg = nodes.get(terminals.get("gate", ""))
        vs = nodes.get(terminals.get("source", ""))
        vb = nodes.get(terminals.get("bulk", ""))

        expected_vgs = item.get("vgs_v")
        expected_vbs = item.get("vbs_v")

        if vg is not None and vs is not None and expected_vgs is not None:
            actual_vgs = (
                vg - vs if polarity == "nmos" else vs - vg
            )
            if abs(actual_vgs - float(expected_vgs)) > tolerance:
                failures.append(f"FINAL_VGS_MISMATCH:{member}")

        if vb is not None and vs is not None and expected_vbs is not None:
            actual_vbs = abs(vb - vs)
            if abs(actual_vbs - abs(float(expected_vbs))) > tolerance:
                failures.append(f"FINAL_VBS_MISMATCH:{member}")

        # A ranged output node may leave VD unresolved. Do not reject it here.
        if vd is None or vs is None:
            continue

        actual_vds = vd - vs if polarity == "nmos" else vs - vd
        minimum_vds = float(
            item.get(
                "minimum_saturated_vds_v",
                item.get("vds_v", 0.0),
            )
        )
        maximum_vds_raw = item.get("maximum_characterized_vds_v")
        maximum_vds = (
            float(maximum_vds_raw)
            if maximum_vds_raw is not None
            else None
        )
        vdsat_raw = item.get("vdsat_v")
        vdsat = float(vdsat_raw) if vdsat_raw is not None else None

        if actual_vds + tolerance < minimum_vds:
            failures.append(f"FINAL_VDS_BELOW_MIN:{member}")
            continue

        if maximum_vds is not None and actual_vds - tolerance > maximum_vds:
            failures.append(f"FINAL_VDS_ABOVE_MAX:{member}")
            continue

        if vdsat is not None and actual_vds + tolerance < vdsat:
            failures.append(f"FINAL_NOT_SATURATED:{member}")

    return failures
'''

if "_final_selected_device_failures(" not in text:
    marker = "\ndef _solve_all_independent_point(\n"
    if marker not in text:
        raise SystemExit(
            "[FAIL] could not find _solve_all_independent_point insertion marker"
        )
    text = text.replace(marker, helper + marker, 1)
    print("[PASS] inserted final device validation helper")
else:
    print("[INFO] final device validation helper already present")

old = '''        if index >= len(groups):
            final_values = dict(current_values)
            for node, value in current_nodes.items():
                final_values.setdefault(f"{node}_v", value)
            if not _declarative_headroom_valid(model, final_values, provenance):
                failures["HEADROOM_CONSTRAINT"] += 1
                return
            exact_vout = "vout_v" in final_values
            solutions.append(
'''

new = '''        if index >= len(groups):
            final_values = dict(current_values)
            for node, value in current_nodes.items():
                final_values.setdefault(f"{node}_v", value)

            # Invalid provisional branches must not consume max_solutions.
            final_device_failures = _final_selected_device_failures(
                model,
                current_nodes,
                provenance,
            )
            if final_device_failures:
                failures.update(final_device_failures)
                return

            if not _declarative_headroom_valid(model, final_values, provenance):
                failures["HEADROOM_CONSTRAINT"] += 1
                return
            exact_vout = "vout_v" in final_values
            solutions.append(
'''

if new in text:
    print("[INFO] leaf validation call already present")
elif old in text:
    text = text.replace(old, new, 1)
    print("[PASS] inserted final validation before solutions.append")
else:
    raise SystemExit(
        "[FAIL] could not locate the completed-branch solution block"
    )

backup = target.with_suffix(target.suffix + ".before_final_validation_fix")
if not backup.exists():
    shutil.copy2(target, backup)

target.write_text(text, encoding="utf-8")
print(f"[PASS] patched: {target}")
print(f"[PASS] backup:  {backup}")

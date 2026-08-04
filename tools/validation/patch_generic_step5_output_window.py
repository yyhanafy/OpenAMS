#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
from pathlib import Path

target = Path(sys.argv[1] if len(sys.argv) > 1 else "src/openams/synthesis/generic_complete_step5.py")
text = target.read_text(encoding="utf-8")

helper = '''

def _intersect_output_device_windows(
    model: Mapping[str, Any],
    values: MutableMapping[str, float],
    nodes: Mapping[str, float],
    provenance: Mapping[str, Any],
) -> bool:
    """Intersect VOUT intervals implied by output-connected MOS devices."""

    devices = _device_map(model)
    tolerance = float(
        model["project_inputs"]["design_rules"]
        .get("technology_intersection", {})
        .get("node_voltage_tolerance_v", 0.025)
    )

    output_nodes: set[str] = {"out", "vout"}
    topology = model.get("topology", {})
    for port in topology.get("ports", []):
        if isinstance(port, str):
            token = port.lower()
            if token in {"out", "vout"}:
                output_nodes.add(token)
        elif isinstance(port, Mapping):
            name = str(port.get("name", port.get("id", port.get("node", "")))).lower()
            direction = str(port.get("direction", port.get("role", ""))).lower()
            if name and (name in {"out", "vout"} or direction == "output" or "output" in direction):
                output_nodes.add(name)

    lower = float(values.get("vout_min_v", -math.inf))
    upper = float(values.get("vout_max_v", math.inf))
    constrained = False

    for member, item in provenance.items():
        device = devices.get(str(member).upper())
        if device is None:
            continue

        terminals = {key: str(value).lower() for key, value in device.get("terminals", {}).items()}
        drain = terminals.get("drain", "")
        source = terminals.get("source", "")
        if drain not in output_nodes:
            continue

        source_value = nodes.get(source)
        if source_value is None:
            return False

        minimum_vds = float(item.get("minimum_saturated_vds_v", item.get("vds_v", 0.0)))
        maximum_vds_raw = item.get("maximum_characterized_vds_v")
        maximum_vds = float(maximum_vds_raw) if maximum_vds_raw is not None else None
        polarity = _polarity(str(device["model"]))

        if polarity == "nmos":
            device_lower = source_value + minimum_vds
            device_upper = source_value + maximum_vds if maximum_vds is not None else math.inf
        else:
            device_lower = source_value - maximum_vds if maximum_vds is not None else -math.inf
            device_upper = source_value - minimum_vds

        lower = max(lower, device_lower)
        upper = min(upper, device_upper)
        constrained = True

        if lower + tolerance >= upper:
            return False

    if constrained:
        values["vout_min_v"] = lower
        values["vout_max_v"] = upper

    return (
        math.isfinite(float(values.get("vout_min_v", lower)))
        and math.isfinite(float(values.get("vout_max_v", upper)))
        and float(values.get("vout_min_v", lower)) < float(values.get("vout_max_v", upper))
    )
'''

if "_intersect_output_device_windows(" not in text:
    marker = "\ndef _final_selected_device_failures(\n"
    if marker not in text:
        raise SystemExit("[FAIL] could not find insertion marker")
    text = text.replace(marker, helper + marker, 1)
    print("[PASS] inserted output-window helper")
else:
    print("[INFO] output-window helper already present")

old = '''            if not _declarative_headroom_valid(model, final_values, provenance):
                failures["HEADROOM_CONSTRAINT"] += 1
                return
            exact_vout = "vout_v" in final_values
'''

new = '''            if not _declarative_headroom_valid(model, final_values, provenance):
                failures["HEADROOM_CONSTRAINT"] += 1
                return

            if not _intersect_output_device_windows(
                model,
                final_values,
                current_nodes,
                provenance,
            ):
                failures["OUTPUT_DEVICE_WINDOW_EMPTY"] += 1
                return

            exact_vout = "vout_v" in final_values
'''

if new in text:
    print("[INFO] leaf output-window call already present")
elif old in text:
    text = text.replace(old, new, 1)
    print("[PASS] inserted output-window intersection")
else:
    raise SystemExit("[FAIL] could not locate leaf headroom block")

backup = target.with_suffix(target.suffix + ".before_output_window_fix")
if not backup.exists():
    shutil.copy2(target, backup)

target.write_text(text, encoding="utf-8")
print(f"[PASS] patched: {target}")
print(f"[PASS] backup:  {backup}")

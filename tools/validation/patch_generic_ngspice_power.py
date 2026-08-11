#!/usr/bin/env python3
from pathlib import Path
import shutil
import yaml

ROOT = Path.home() / "AMS-Tutorial" / "openams"
ENGINE = ROOT / "src/openams/validation/ngspice_witness.py"
PLAN = ROOT / "examples/two_stage_opamp/inputs/ngspice_validation.yaml"

def backup(path, suffix):
    bak = path.with_suffix(path.suffix + suffix)
    shutil.copy2(path, bak)
    return bak

def must_replace(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"{label}: expected block not found")
    return text.replace(old, new, 1)

def patch_engine():
    s = ENGINE.read_text(encoding="utf-8")

    if 'plan.get("measurements")' not in s:
        old = (
            '    for name, spec in plan.get("nodes", {}).items():\n'
            '        lines.append(f\'echo "__OPENAMS_{name.upper()}__"\')\n'
            '        lines.append(f\'print {spec["ngspice"]}\')\n'
            '\n'
            '    ac = plan.get("ac") or {}\n'
        )
        new = (
            '    for name, spec in plan.get("nodes", {}).items():\n'
            '        lines.append(f\'echo "__OPENAMS_{name.upper()}__"\')\n'
            '        lines.append(f\'print {spec["ngspice"]}\')\n'
            '\n'
            '    for name, spec in (plan.get("measurements") or {}).items():\n'
            '        lines.append(f\'echo "__OPENAMS_{name.upper()}__"\')\n'
            '        lines.append(f\'print {spec["ngspice"]}\')\n'
            '\n'
            '    ac = plan.get("ac") or {}\n'
        )
        s = must_replace(s, old, new, "deck measurements")

    if "measurement_names =" not in s:
        old = (
            '    node_names = list((plan.get("nodes") or {}).keys())\n'
            '    fields = ["selection_rank", "point_index", "witness_rank", "ngspice_rc", "ngspice_elapsed_s"]\n'
        )
        new = (
            '    node_names = list((plan.get("nodes") or {}).keys())\n'
            '    measurement_names = list((plan.get("measurements") or {}).keys())\n'
            '    parse_names = node_names + measurement_names\n'
            '    fields = ["selection_rank", "point_index", "witness_rank", "ngspice_rc", "ngspice_elapsed_s"]\n'
        )
        s = must_replace(s, old, new, "measurement names")

    if "fields += measurement_names" not in s:
        old = (
            '    for name in node_names:\n'
            '        fields += [f"mlp_{name}_v", f"ng_{name}_v", f"delta_{name}_v"]\n'
            '    fields += ["max_abs_voltage_delta_v", "dc_validation_status", "ac_gain_db", "ac_ugb_hz", "ac_phase_margin_deg", "validation_status"]\n'
        )
        new = (
            '    for name in node_names:\n'
            '        fields += [f"mlp_{name}_v", f"ng_{name}_v", f"delta_{name}_v"]\n'
            '    fields += measurement_names\n'
            '    if plan.get("power"):\n'
            '        fields += ["power_w"]\n'
            '    fields += ["max_abs_voltage_delta_v", "dc_validation_status", "ac_gain_db", "ac_ugb_hz", "ac_phase_margin_deg", "validation_status"]\n'
        )
        s = must_replace(s, old, new, "result fields")

    if "parsed_values = _parse_tagged_values" not in s:
        old = (
            '                nodes = _parse_tagged_values(proc.stdout + "\\n" + proc.stderr, node_names)\n'
            '                ac_metrics = _parse_ac_raw(ac_path) if (plan.get("ac") or {}).get("enabled", False) and proc.returncode == 0 else {}\n'
        )
        new = (
            '                parsed_values = _parse_tagged_values(proc.stdout + "\\n" + proc.stderr, parse_names)\n'
            '                nodes = {name: parsed_values[name] for name in node_names if name in parsed_values}\n'
            '                measurements = {name: parsed_values[name] for name in measurement_names if name in parsed_values}\n'
            '                ac_metrics = _parse_ac_raw(ac_path) if (plan.get("ac") or {}).get("enabled", False) and proc.returncode == 0 else {}\n'
        )
        s = must_replace(s, old, new, "tag parsing")

    if 'current_name = power["current_measurement"]' not in s:
        old = (
            '            maximum = max(deltas) if deltas else float("nan")\n'
            '            tolerance = float(plan.get("dc_tolerance_v", 0.05))\n'
        )
        new = (
            '            for name, spec in (plan.get("measurements") or {}).items():\n'
            '                value = measurements.get(name, float("nan"))\n'
            '                if spec.get("absolute", False) and np.isfinite(value):\n'
            '                    value = abs(value)\n'
            '                record[name] = value\n'
            '\n'
            '            power = plan.get("power") or {}\n'
            '            if power:\n'
            '                current_name = power["current_measurement"]\n'
            '                current = record.get(current_name, float("nan"))\n'
            '                supply_voltage = float(power.get("supply_voltage_v", 0.0))\n'
            '                record["power_w"] = abs(supply_voltage) * abs(current) if np.isfinite(current) else float("nan")\n'
            '\n'
            '            maximum = max(deltas) if deltas else float("nan")\n'
            '            tolerance = float(plan.get("dc_tolerance_v", 0.05))\n'
        )
        s = must_replace(s, old, new, "power calculation")

    bak = backup(ENGINE, ".before_generic_measurements.bak")
    ENGINE.write_text(s, encoding="utf-8")
    print("engine backup:", bak)
    print("engine patched:", ENGINE)

def patch_plan():
    plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    plan["input_csv"] = "examples/two_stage_opamp/generated/assignment_synthesis/two_stage_all_2025_mlp_witnesses_full.csv"
    plan["measurements"] = {
        "supply_current_a": {
            "ngspice": "vdd_src#branch",
            "absolute": True,
        }
    }
    plan["power"] = {
        "supply_voltage_v": 1.8,
        "current_measurement": "supply_current_a",
    }
    bak = backup(PLAN, ".before_power_measurement.bak")
    PLAN.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    print("plan backup:", bak)
    print("plan patched:", PLAN)

if __name__ == "__main__":
    if not ENGINE.is_file():
        raise SystemExit(f"missing generic validator: {ENGINE}")
    if not PLAN.is_file():
        raise SystemExit(f"missing validation plan: {PLAN}")
    patch_engine()
    patch_plan()

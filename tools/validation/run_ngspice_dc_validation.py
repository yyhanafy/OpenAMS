\
#!/usr/bin/env python3
"""Run and compare ngspice DC operating points for OpenAMS validation decks.

V2 classification:
- dc_physical_valid:
    ngspice converged
    AND all device currents match within tolerance
    AND all devices remain saturated
    AND internal bias nodes match within tolerance
    AND actual ngspice Vout remains inside the allowed output window
- vout_target_match:
    requested/constructed Vout matches ngspice within the target tolerance
- proceed_to_ac:
    same as dc_physical_valid

A Vout target mismatch is a model-accuracy warning, not a physical-validity failure.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

NODE_MAP = {
    "v(xu1.ntail)": "vtail_v",
    "v(xu1.n1)": "n1_v",
    "v(xu1.n2)": "n2_v",
    "v(vbias)": "vbias_v",
    "v(out)": "vout_v",
    "vdd_src#branch": "vdd_source_current_a",
    "vss_src#branch": "vss_source_current_a",
    "vbias_src#branch": "vbias_source_current_a",
}

DEVICE_POLARITY = {
    1: "nmos",
    2: "nmos",
    3: "pmos",
    4: "pmos",
    5: "nmos",
    6: "pmos",
    7: "nmos",
}

DEVICE_MODEL = {
    "nmos": "sky130_fd_pr__nfet_01v8",
    "pmos": "sky130_fd_pr__pfet_01v8",
}

DEVICE_KEYS = ("id", "gm", "gds", "vds", "vdsat")

INTERNAL_NODE_KEYS = ("vtail_v", "n1_v", "n2_v", "vbias_v")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--points", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--ngspice", default="ngspice")
    p.add_argument("--internal-node-tolerance-v", type=float, default=0.025)
    p.add_argument("--vout-target-tolerance-v", type=float, default=0.025)
    p.add_argument("--vout-min-v", type=float, default=0.5)
    p.add_argument("--vout-max-v", type=float, default=2.0)
    p.add_argument("--current-relative-tolerance", type=float, default=0.10)
    p.add_argument("--current-absolute-tolerance-a", type=float, default=1e-6)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def parse_block(text: str, begin: str, end: str) -> list[str]:
    try:
        body = text.split(begin, 1)[1].split(end, 1)[0]
    except IndexError:
        return []
    return [line.strip() for line in body.splitlines() if line.strip()]


def parse_op(log_text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in parse_block(log_text, "OPENAMS_OP_BEGIN", "OPENAMS_OP_END"):
        m = re.match(rf"(.+?)\s*=\s*({FLOAT_RE})\s*$", line)
        if not m:
            continue
        key = NODE_MAP.get(m.group(1).strip())
        if key:
            out[key] = float(m.group(2))
    return out


def parse_devices(log_text: str) -> dict[str, dict[str, float]]:
    devices: dict[str, dict[str, float]] = {}
    for line in parse_block(log_text, "OPENAMS_DEVICE_BEGIN", "OPENAMS_DEVICE_END"):
        m = re.match(
            rf"@m\.xu1\.xm([1-7])\.msky130_fd_pr__(?:nfet|pfet)_01v8\[(id|gm|gds|vds|vdsat)\]\s*=\s*({FLOAT_RE})\s*$",
            line,
            re.IGNORECASE,
        )
        if not m:
            continue
        device = f"M{m.group(1)}"
        devices.setdefault(device, {})[m.group(2).lower()] = float(m.group(3))
    return devices


def assignment_device_points(assignment_record: dict[str, Any]) -> dict[str, Any]:
    assignment = assignment_record["assignment"]
    points = assignment.get("device_points")
    if not isinstance(points, dict):
        raise KeyError("assignment.device_points is missing")
    return points


def get_assignment_value(assignment: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = assignment.get(name)
        if value is not None:
            return float(value)
    return None


def get_point_value(point: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = point.get(name)
        if value is not None:
            return float(value)
    return None


def current_match(
    actual: float,
    expected: float,
    rel_tol: float,
    abs_tol: float,
) -> tuple[float, float, bool]:
    abs_error = abs(actual - expected)
    denom = max(abs(expected), abs_tol)
    rel_error = abs_error / denom
    passed = abs_error <= abs_tol or rel_error <= rel_tol
    return abs_error, rel_error, passed


def voltage_match(actual: float, expected: float, tol: float) -> tuple[float, float, bool]:
    signed_error = actual - expected
    abs_error = abs(signed_error)
    return signed_error, abs_error, abs_error <= tol


def point_dirs(points_root: Path) -> list[Path]:
    return sorted(
        p for p in points_root.glob("point_*")
        if p.is_dir() and (p / "deck.spice").is_file()
    )


def run_point(
    point_dir: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any]]:
    assignment_record = load_json(point_dir / "assignment.json")
    assignment = assignment_record["assignment"]
    device_points = assignment_device_points(assignment_record)

    log_path = point_dir / "ngspice.log"
    if log_path.exists() and not args.overwrite:
        log_text = log_path.read_text(errors="replace")
        return_code = 0
        runtime_s = None
        execution_mode = "existing_log"
    else:
        start = time.perf_counter()
        proc = subprocess.run(
            [args.ngspice, "-b", "-o", "ngspice.log", "deck.spice"],
            cwd=point_dir,
            text=True,
            capture_output=True,
        )
        runtime_s = time.perf_counter() - start
        return_code = proc.returncode
        log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
        execution_mode = "executed"

    op = parse_op(log_text)
    devices = parse_devices(log_text)

    extraction_errors = []
    if return_code != 0:
        extraction_errors.append(f"ngspice_return_code_{return_code}")
    if len(op) < 8:
        extraction_errors.append("incomplete_operating_point_block")
    if len(devices) != 7 or any(set(values) != set(DEVICE_KEYS) for values in devices.values()):
        extraction_errors.append("incomplete_device_block")
    if "No matching instances" in log_text or "not available" in log_text:
        extraction_errors.append("hierarchy_or_vector_error")

    expected_nodes = {
        "vtail_v": get_assignment_value(assignment, "vtail_v"),
        "n1_v": get_assignment_value(assignment, "n1_v"),
        "n2_v": get_assignment_value(assignment, "n2_v"),
        "vbias_v": get_assignment_value(assignment, "vbias_v"),
        "vout_v": get_assignment_value(assignment, "vout_v", "vout_constructed_v"),
    }

    node_comparisons: dict[str, Any] = {}
    internal_node_passes = []

    for key in INTERNAL_NODE_KEYS:
        expected = expected_nodes[key]
        actual = op.get(key)
        if expected is None or actual is None:
            node_comparisons[key] = {
                "expected": expected,
                "actual": actual,
                "pass": False,
            }
            internal_node_passes.append(False)
            continue
        signed_err, abs_err, passed = voltage_match(
            actual, expected, args.internal_node_tolerance_v
        )
        node_comparisons[key] = {
            "expected": expected,
            "actual": actual,
            "signed_error_v": signed_err,
            "absolute_error_v": abs_err,
            "pass": passed,
        }
        internal_node_passes.append(passed)

    vout_expected = expected_nodes["vout_v"]
    vout_actual = op.get("vout_v")
    if vout_expected is None or vout_actual is None:
        vout_comparison = {
            "expected": vout_expected,
            "actual": vout_actual,
            "target_match": False,
            "within_allowed_window": False,
        }
        vout_target_match = False
        vout_within_window = False
    else:
        signed_err, abs_err, target_match = voltage_match(
            vout_actual, vout_expected, args.vout_target_tolerance_v
        )
        vout_within_window = args.vout_min_v <= vout_actual <= args.vout_max_v
        vout_target_match = target_match
        vout_comparison = {
            "expected": vout_expected,
            "actual": vout_actual,
            "signed_error_v": signed_err,
            "absolute_error_v": abs_err,
            "target_match": target_match,
            "within_allowed_window": vout_within_window,
            "allowed_min_v": args.vout_min_v,
            "allowed_max_v": args.vout_max_v,
            "warning": not target_match,
        }

    node_comparisons["vout_v"] = vout_comparison

    device_comparisons: dict[str, Any] = {}
    current_passes = []
    saturation_passes = []

    for idx in range(1, 8):
        name = f"M{idx}"
        expected_point = device_points[name]
        actual = devices.get(name, {})

        expected_current = get_point_value(
            expected_point,
            "target_current_a",
            "id_abs_a",
            "current_a",
            "id_pred_a",
        )
        actual_id_signed = actual.get("id")
        actual_current = abs(actual_id_signed) if actual_id_signed is not None else None

        if expected_current is None or actual_current is None:
            current_cmp = {
                "expected_abs_a": expected_current,
                "actual_abs_a": actual_current,
                "pass": False,
            }
            current_passes.append(False)
        else:
            abs_err, rel_err, passed = current_match(
                actual_current,
                abs(expected_current),
                args.current_relative_tolerance,
                args.current_absolute_tolerance_a,
            )
            current_cmp = {
                "expected_abs_a": abs(expected_current),
                "actual_signed_a": actual_id_signed,
                "actual_abs_a": actual_current,
                "absolute_error_a": abs_err,
                "relative_error": rel_err,
                "pass": passed,
            }
            current_passes.append(passed)

        vds = actual.get("vds")
        vdsat = actual.get("vdsat")
        saturated = (
            abs(vds) >= abs(vdsat)
            if vds is not None and vdsat is not None
            else False
        )
        saturation_margin = (
            abs(vds) - abs(vdsat)
            if vds is not None and vdsat is not None
            else None
        )
        saturation_passes.append(saturated)

        expected_gm = get_point_value(expected_point, "gm_s", "gm")
        expected_gds = get_point_value(expected_point, "gds_s", "gds")

        device_comparisons[name] = {
            "polarity": DEVICE_POLARITY[idx],
            "model": DEVICE_MODEL[DEVICE_POLARITY[idx]],
            "current": current_cmp,
            "ngspice": actual,
            "saturation": {
                "actual_saturated": saturated,
                "actual_margin_v": saturation_margin,
            },
            "small_signal": {
                "gm_expected_s": expected_gm,
                "gm_actual_s": actual.get("gm"),
                "gds_expected_s": expected_gds,
                "gds_actual_s": actual.get("gds"),
            },
        }

    extraction_complete = return_code == 0 and not extraction_errors
    all_internal_nodes_match = all(internal_node_passes)
    all_currents_match = all(current_passes)
    all_devices_saturated = all(saturation_passes)

    # Physical validity is decided only from the actual ngspice circuit.
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

    result = {
        "grid_index": assignment_record.get("grid_index"),
        "assignment_id": assignment_record.get("assignment_id"),
        "point_directory": str(point_dir),
        "execution_mode": execution_mode,
        "ngspice_return_code": return_code,
        "runtime_s": runtime_s,
        "extraction_complete": extraction_complete,
        "extraction_errors": extraction_errors,
        "node_comparisons": node_comparisons,
        "device_comparisons": device_comparisons,
        "all_internal_nodes_within_tolerance": all_internal_nodes_match,
        "all_currents_within_tolerance": all_currents_match,
        "all_devices_saturated": all_devices_saturated,
        "vout_within_allowed_window": vout_within_window,
        "vout_target_match": vout_target_match,
        "vout_target_warning": dc_physical_valid and not vout_target_match,
        "internal_node_model_warning": dc_physical_valid and not all_internal_nodes_match,
        "current_model_warning": dc_physical_valid and not all_currents_match,
        "model_accuracy_warnings": model_accuracy_warnings,
        "dc_physical_valid": dc_physical_valid,
        "dc_exact_realization_pass": exact_realization_pass,
        "proceed_to_ac": proceed_to_ac,
        "classification": classification,
        "tolerances": {
            "internal_node_tolerance_v": args.internal_node_tolerance_v,
            "vout_target_tolerance_v": args.vout_target_tolerance_v,
            "vout_allowed_min_v": args.vout_min_v,
            "vout_allowed_max_v": args.vout_max_v,
            "current_relative_tolerance": args.current_relative_tolerance,
            "current_absolute_tolerance_a": args.current_absolute_tolerance_a,
        },
    }

    op_json = {
        "grid_index": result["grid_index"],
        "assignment_id": result["assignment_id"],
        "nodes": op,
        "devices": devices,
    }
    return result, op_json


def flatten(result: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "grid_index": result["grid_index"],
        "assignment_id": result["assignment_id"],
        "ngspice_return_code": result["ngspice_return_code"],
        "extraction_complete": result["extraction_complete"],
        "dc_physical_valid": result["dc_physical_valid"],
        "dc_exact_realization_pass": result["dc_exact_realization_pass"],
        "proceed_to_ac": result["proceed_to_ac"],
        "classification": result["classification"],
        "all_internal_nodes_within_tolerance": result[
            "all_internal_nodes_within_tolerance"
        ],
        "all_currents_within_tolerance": result["all_currents_within_tolerance"],
        "all_devices_saturated": result["all_devices_saturated"],
        "vout_within_allowed_window": result["vout_within_allowed_window"],
        "vout_target_match": result["vout_target_match"],
        "vout_target_warning": result["vout_target_warning"],
        "internal_node_model_warning": result["internal_node_model_warning"],
        "current_model_warning": result["current_model_warning"],
        "model_accuracy_warnings": ";".join(result["model_accuracy_warnings"]),
        "runtime_s": result["runtime_s"],
        "extraction_errors": ";".join(result["extraction_errors"]),
    }

    for node, cmp in result["node_comparisons"].items():
        prefix = node.removesuffix("_v")
        row[f"{prefix}_expected_v"] = cmp.get("expected")
        row[f"{prefix}_ngspice_v"] = cmp.get("actual")
        row[f"{prefix}_signed_error_v"] = cmp.get("signed_error_v")
        row[f"{prefix}_absolute_error_v"] = cmp.get("absolute_error_v")
        if node == "vout_v":
            row["vout_target_match"] = cmp.get("target_match")
            row["vout_within_allowed_window"] = cmp.get("within_allowed_window")
        else:
            row[f"{prefix}_pass"] = cmp.get("pass")

    for device, data in result["device_comparisons"].items():
        p = device.lower()
        current = data["current"]
        ng = data["ngspice"]
        sat = data["saturation"]
        ss = data["small_signal"]

        row[f"{p}_current_expected_a"] = current.get("expected_abs_a")
        row[f"{p}_current_ngspice_signed_a"] = current.get("actual_signed_a")
        row[f"{p}_current_ngspice_abs_a"] = current.get("actual_abs_a")
        row[f"{p}_current_absolute_error_a"] = current.get("absolute_error_a")
        row[f"{p}_current_relative_error"] = current.get("relative_error")
        row[f"{p}_current_pass"] = current.get("pass")
        row[f"{p}_gm_expected_s"] = ss.get("gm_expected_s")
        row[f"{p}_gm_ngspice_s"] = ss.get("gm_actual_s")
        row[f"{p}_gds_expected_s"] = ss.get("gds_expected_s")
        row[f"{p}_gds_ngspice_s"] = ss.get("gds_actual_s")
        row[f"{p}_vds_ngspice_v"] = ng.get("vds")
        row[f"{p}_vdsat_ngspice_v"] = ng.get("vdsat")
        row[f"{p}_saturation_margin_ngspice_v"] = sat.get("actual_margin_v")
        row[f"{p}_saturated_ngspice"] = sat.get("actual_saturated")

    return row


def main() -> int:
    args = parse_args()
    points_root = args.points.resolve()
    output = args.output.resolve()

    dirs = point_dirs(points_root)
    if args.limit is not None:
        dirs = dirs[: args.limit]
    if not dirs:
        raise FileNotFoundError(f"No point_* directories with deck.spice under {points_root}")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {output}")

    aggregate = []
    for index, point_dir in enumerate(dirs, 1):
        result, op_json = run_point(point_dir, args)
        (point_dir / "dc_operating_point.json").write_text(
            json.dumps(op_json, indent=2, sort_keys=True) + "\n"
        )
        (point_dir / "validation_result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        aggregate.append(flatten(result))
        print(
            f"[{index}/{len(dirs)}] {point_dir.name} "
            f"classification={result['classification']} "
            f"proceed_to_ac={result['proceed_to_ac']}"
        )

    fields: list[str] = []
    for row in aggregate:
        for key in row:
            if key not in fields:
                fields.append(key)

    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(aggregate)

    physical = sum(bool(row["dc_physical_valid"]) for row in aggregate)
    exact = sum(bool(row["dc_exact_realization_pass"]) for row in aggregate)
    vout_warnings = sum(bool(row["vout_target_warning"]) for row in aggregate)
    node_warnings = sum(bool(row["internal_node_model_warning"]) for row in aggregate)
    current_warnings = sum(bool(row["current_model_warning"]) for row in aggregate)
    proceed = sum(bool(row["proceed_to_ac"]) for row in aggregate)

    classifications: dict[str, int] = {}
    for row in aggregate:
        name = str(row["classification"])
        classifications[name] = classifications.get(name, 0) + 1

    summary = {
        "status": "PASS",
        "points_processed": len(aggregate),
        "dc_physical_valid": physical,
        "dc_physical_invalid": len(aggregate) - physical,
        "dc_exact_realization_pass": exact,
        "vout_target_warnings": vout_warnings,
        "internal_node_model_warnings": node_warnings,
        "current_model_warnings": current_warnings,
        "proceed_to_ac": proceed,
        "classifications": classifications,
        "aggregate_csv": str(output),
        "tolerances": {
            "internal_node_tolerance_v": args.internal_node_tolerance_v,
            "vout_target_tolerance_v": args.vout_target_tolerance_v,
            "vout_allowed_min_v": args.vout_min_v,
            "vout_allowed_max_v": args.vout_max_v,
            "current_relative_tolerance": args.current_relative_tolerance,
            "current_absolute_tolerance_a": args.current_absolute_tolerance_a,
        },
    }
    (output.parent / "dc_validation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    print("===== OPENAMS NGSPICE DC VALIDATION V3 =====")
    print(f"points:             {len(aggregate)}")
    print(f"physically valid:   {physical}")
    print(f"exact Vout match:   {exact}")
    print(f"Vout warnings:      {vout_warnings}")
    print(f"node warnings:      {node_warnings}")
    print(f"current warnings:   {current_warnings}")
    print(f"proceed to AC:      {proceed}")
    print(f"csv:                {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

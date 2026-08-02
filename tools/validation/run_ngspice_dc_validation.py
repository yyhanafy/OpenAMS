\
#!/usr/bin/env python3
"""Run and compare ngspice DC operating points for OpenAMS validation decks."""

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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--points", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--ngspice", default="ngspice")
    p.add_argument("--voltage-tolerance-v", type=float, default=0.025)
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


def voltage_match(actual: float, expected: float, tol: float) -> tuple[float, bool]:
    err = abs(actual - expected)
    return err, err <= tol


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

    errors = []
    if return_code != 0:
        errors.append(f"ngspice_return_code_{return_code}")
    if len(op) < 8:
        errors.append("incomplete_operating_point_block")
    if len(devices) != 7 or any(set(values) != set(DEVICE_KEYS) for values in devices.values()):
        errors.append("incomplete_device_block")
    if "No matching instances" in log_text or "not available" in log_text:
        errors.append("hierarchy_or_vector_error")

    expected_nodes = {
        "vtail_v": get_assignment_value(assignment, "vtail_v"),
        "n1_v": get_assignment_value(assignment, "n1_v"),
        "n2_v": get_assignment_value(assignment, "n2_v"),
        "vbias_v": get_assignment_value(assignment, "vbias_v"),
        "vout_v": get_assignment_value(assignment, "vout_v", "vout_constructed_v"),
    }

    node_comparisons: dict[str, Any] = {}
    node_passes = []
    for key, expected in expected_nodes.items():
        actual = op.get(key)
        if expected is None or actual is None:
            node_comparisons[key] = {"expected": expected, "actual": actual, "pass": False}
            node_passes.append(False)
            continue
        err, passed = voltage_match(actual, expected, args.voltage_tolerance_v)
        node_comparisons[key] = {
            "expected": expected,
            "actual": actual,
            "absolute_error_v": err,
            "pass": passed,
        }
        node_passes.append(passed)

    device_comparisons: dict[str, Any] = {}
    current_passes = []
    saturation_passes = []
    gm_gds_rows = {}

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

        current_cmp: dict[str, Any]
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

        gm_gds_rows[name] = {
            "gm_expected_s": expected_gm,
            "gm_actual_s": actual.get("gm"),
            "gds_expected_s": expected_gds,
            "gds_actual_s": actual.get("gds"),
        }

        device_comparisons[name] = {
            "polarity": DEVICE_POLARITY[idx],
            "model": DEVICE_MODEL[DEVICE_POLARITY[idx]],
            "current": current_cmp,
            "ngspice": actual,
            "saturation": {
                "actual_saturated": saturated,
                "actual_margin_v": saturation_margin,
            },
            "small_signal": gm_gds_rows[name],
        }

    converged = return_code == 0 and not errors
    dc_pass = converged and all(node_passes) and all(current_passes) and all(saturation_passes)

    result = {
        "grid_index": assignment_record.get("grid_index"),
        "assignment_id": assignment_record.get("assignment_id"),
        "point_directory": str(point_dir),
        "execution_mode": execution_mode,
        "ngspice_return_code": return_code,
        "runtime_s": runtime_s,
        "converged": converged,
        "errors": errors,
        "node_comparisons": node_comparisons,
        "device_comparisons": device_comparisons,
        "all_nodes_within_tolerance": all(node_passes),
        "all_currents_within_tolerance": all(current_passes),
        "all_devices_saturated": all(saturation_passes),
        "dc_validation_pass": dc_pass,
        "tolerances": {
            "voltage_tolerance_v": args.voltage_tolerance_v,
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
        "converged": result["converged"],
        "dc_validation_pass": result["dc_validation_pass"],
        "all_nodes_within_tolerance": result["all_nodes_within_tolerance"],
        "all_currents_within_tolerance": result["all_currents_within_tolerance"],
        "all_devices_saturated": result["all_devices_saturated"],
        "runtime_s": result["runtime_s"],
        "errors": ";".join(result["errors"]),
    }

    for node, cmp in result["node_comparisons"].items():
        prefix = node.removesuffix("_v")
        row[f"{prefix}_expected_v"] = cmp.get("expected")
        row[f"{prefix}_ngspice_v"] = cmp.get("actual")
        row[f"{prefix}_absolute_error_v"] = cmp.get("absolute_error_v")
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
            f"converged={result['converged']} "
            f"dc_pass={result['dc_validation_pass']}"
        )

    fields = []
    for row in aggregate:
        for key in row:
            if key not in fields:
                fields.append(key)

    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(aggregate)

    passed = sum(bool(row["dc_validation_pass"]) for row in aggregate)
    summary = {
        "status": "PASS",
        "points_processed": len(aggregate),
        "dc_validation_passed": passed,
        "dc_validation_failed": len(aggregate) - passed,
        "aggregate_csv": str(output),
        "tolerances": {
            "voltage_tolerance_v": args.voltage_tolerance_v,
            "current_relative_tolerance": args.current_relative_tolerance,
            "current_absolute_tolerance_a": args.current_absolute_tolerance_a,
        },
    }
    (output.parent / "dc_validation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    print("===== OPENAMS NGSPICE DC VALIDATION =====")
    print(f"points: {len(aggregate)}")
    print(f"passed: {passed}")
    print(f"failed: {len(aggregate) - passed}")
    print(f"csv:    {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

NUM = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _value(row: dict[str, str], key: str, default=None) -> float:
    raw = row.get(key, "")
    if raw not in ("", None):
        return float(raw)
    if default is not None:
        return float(default)
    raise KeyError(key)


def _safe_eval(expr: Any, env: dict[str, Any]):
    return eval(str(expr), {"__builtins__": {}}, {"np": np, **env})


def _discover_library(plan: dict[str, Any]) -> Path:
    explicit = plan.get("pdk", {}).get("library")
    if explicit and str(explicit).upper() != "AUTO":
        path = Path(explicit).expanduser()
        if path.exists():
            return path.resolve()
        raise FileNotFoundError(path)

    candidates: list[Path] = []
    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        candidates.extend(
            [
                Path(pdk_root) / "sky130A/libs.tech/ngspice/sky130.lib.spice",
                Path(pdk_root) / "sky130B/libs.tech/ngspice/sky130.lib.spice",
            ]
        )
    candidates.extend(
        [
            Path("/usr/share/pdk/sky130A/libs.tech/ngspice/sky130.lib.spice"),
            Path("/usr/local/share/pdk/sky130A/libs.tech/ngspice/sky130.lib.spice"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError("SKY130 ngspice library not found; set PDK_ROOT or pdk.library")


def _render_source(source: Path, bindings: dict[str, Any], env: dict[str, Any], target: Path) -> Path:
    text = source.read_text(encoding="utf-8")
    values = {key: _safe_eval(expr, env) for key, expr in bindings.items()}
    target.write_text(text.format_map(values), encoding="utf-8")
    return target


def _parse_tagged_values(stdout: str, names: list[str]) -> dict[str, float]:
    tags = {f"__OPENAMS_{name.upper()}__": name for name in names}
    lines = stdout.splitlines()
    values: dict[str, float] = {}
    for i, line in enumerate(lines):
        tag = line.strip()
        if tag not in tags:
            continue
        name = tags[tag]
        for later in lines[i + 1 : i + 9]:
            stripped = later.strip()
            if stripped.startswith("__OPENAMS_"):
                break
            if "=" in stripped:
                match = NUM.search(stripped.split("=", 1)[1])
                if match:
                    values[name] = float(match.group(0))
                    break
    return values


def _parse_ac_raw(path: Path, output_name: str, transfer_sign: float = 1.0) -> dict[str, float]:
    if not path.exists() or path.stat().st_size == 0:
        return {}

    lines = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    nvars = None
    npoints = None
    var_start = None
    value_start = None

    for i, line in enumerate(lines):
        text = line.strip()
        low = text.lower()

        if low.startswith("no. variables:"):
            nvars = int(text.split(":", 1)[1].strip())
        elif low.startswith("no. points:"):
            npoints = int(text.split(":", 1)[1].strip())
        elif text == "Variables:":
            var_start = i + 1
        elif text == "Values:":
            value_start = i + 1
            break

    if not nvars or not npoints or var_start is None or value_start is None:
        return {}

    names = []
    for line in lines[var_start:var_start + nvars]:
        tokens = line.split()
        if len(tokens) < 2:
            return {}
        names.append(tokens[1].strip().lower())

    try:
        fi = names.index("frequency")
    except ValueError:
        return {}

    wanted = str(output_name).strip().lower()
    try:
        oi = names.index(wanted)
    except ValueError:
        return {}

    def parse_complex_line(text: str) -> complex:
        text = text.strip()

        # First line of each point may start with the integer point index.
        parts = text.split(None, 1)
        payload = parts[-1] if len(parts) > 1 else parts[0]

        if "," in payload:
            real_text, imag_text = payload.split(",", 1)
            return complex(float(real_text), float(imag_text))

        return complex(float(payload), 0.0)

    data = []
    cursor = value_start

    for _ in range(npoints):
        point = []

        while cursor < len(lines) and len(point) < nvars:
            text = lines[cursor].strip()
            cursor += 1

            if not text:
                continue

            try:
                value = parse_complex_line(text)
            except Exception:
                continue

            point.append(value)

        if len(point) == nvars:
            data.append(point)

    if not data:
        return {}

    arr = np.asarray(data, dtype=complex)

    freq = np.real(arr[:, fi])
    out = arr[:, oi]

    valid = (
        np.isfinite(freq)
        & (freq > 0)
        & np.isfinite(np.real(out))
        & np.isfinite(np.imag(out))
    )

    freq = freq[valid]
    out = out[valid]

    if len(freq) < 2:
        return {}

    order = np.argsort(freq)
    freq = freq[order]
    out = out[order]

    # Normalize the measured transfer-function polarity before extracting
    # phase.  This is plan-configurable so every topology uses the same PM
    # implementation without topology-specific phase hacks.
    sign = float(transfer_sign)
    if sign not in (-1.0, 1.0):
        raise ValueError(f"transfer_sign must be +1 or -1, got {sign}")
    out = sign * out

    magnitude = np.abs(out)
    gain_db = 20.0 * np.log10(np.maximum(magnitude, 1e-300))
    phase_deg = np.rad2deg(np.unwrap(np.angle(out)))

    result = {
        "ac_gain_db": float(gain_db[0]),
        "ac_phase_low_frequency_deg": float(phase_deg[0]),
    }

    bw_target = gain_db[0] - 3.0
    for i in range(len(freq) - 1):
        if gain_db[i] >= bw_target and gain_db[i + 1] <= bw_target:
            y0, y1 = gain_db[i], gain_db[i + 1]
            alpha = (bw_target - y0) / (y1 - y0) if y1 != y0 else 0.0
            logf = np.log10(freq[i]) + alpha * (
                np.log10(freq[i + 1]) - np.log10(freq[i])
            )
            result["ac_bandwidth_3db_hz"] = float(10 ** logf)
            break

    crossing = None
    for i in range(len(freq) - 1):
        if gain_db[i] >= 0.0 and gain_db[i + 1] <= 0.0:
            crossing = i
            break

    if crossing is not None:
        i = crossing
        y0, y1 = gain_db[i], gain_db[i + 1]
        alpha = (0.0 - y0) / (y1 - y0) if y1 != y0 else 0.0

        logf = np.log10(freq[i]) + alpha * (
            np.log10(freq[i + 1]) - np.log10(freq[i])
        )

        phase_cross = phase_deg[i] + alpha * (
            phase_deg[i + 1] - phase_deg[i]
        )

        result["ac_ugb_hz"] = float(10 ** logf)
        result["ac_phase_at_ugb_deg"] = float(phase_cross)
        result["ac_phase_margin_deg"] = float(180.0 + phase_cross)

    return result


def _build_deck(plan: dict[str, Any], row: dict[str, str], source: Path, lib: Path, ac_path: Path) -> str:
    env: dict[str, Any] = {key: float(value) for key, value in (plan.get("constants") or {}).items()}
    env.update({key: _value(row, key) for key in row if row.get(key, "") not in ("", None) and _is_float(row[key])})

    lines = [
        "* OpenAMS generic witness validation",
        f'.lib "{lib}" {plan.get("pdk", {}).get("corner", "tt")}',
        f'.temp {float(plan.get("temperature_c", 27.0))}',
        ".option savecurrents",
    ]
    for name, expression in (plan.get("parameters") or {}).items():
        lines.append(f".param {name}={_safe_eval(expression, env):.15g}")
    lines.append(f'.include "{source}"')
    lines.extend(str(plan["circuit"]).format_map(env).splitlines())
    lines.append(".control")
    lines.append("set noaskquit")
    lines.append("op")
    for name, spec in plan.get("nodes", {}).items():
        lines.append(f'echo "__OPENAMS_{name.upper()}__"')
        lines.append(f'print {spec["ngspice"]}')

    for name, spec in (plan.get("measurements") or {}).items():
        lines.append(f'echo "__OPENAMS_{name.upper()}__"')
        lines.append(f'print {spec["ngspice"]}')

    ac = plan.get("ac") or {}
    if ac.get("enabled", False):
        sweep = ac.get("sweep", {})
        lines.append(
            f'ac dec {int(sweep.get("points_per_decade", 100))} '
            f'{float(sweep.get("start_hz", 1.0)):.15g} '
            f'{float(sweep.get("stop_hz", 1e9)):.15g}'
        )
        lines.append("set filetype=ascii")
        lines.append(f'write {ac_path} frequency {ac["output"]}')
    lines.extend(["quit", ".endc", ".end", ""])
    return "\n".join(lines)


def _is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def validate(plan_path: Path, root: Path, *, top_n: int | None = None, output_csv: Path | None = None, ngspice: str = "ngspice") -> Path:
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    resolve = lambda p: Path(p) if Path(p).is_absolute() else root / Path(p)
    input_csv = resolve(plan["input_csv"])
    source_netlist = resolve(plan["source_netlist"])
    output_path = output_csv or resolve(plan["output_csv"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    library = _discover_library(plan)

    with input_csv.open(newline="", encoding="utf-8") as stream:
        rows = [row for row in csv.DictReader(stream) if row.get(plan.get("status_column", "generation_status")) == plan.get("status_value", "WITNESS")]
    rank_by = plan.get("rank_by", ["max_abs_residual", "rms_residual"])
    rows.sort(key=lambda row: tuple(float(row[key]) for key in rank_by))
    limit = top_n if top_n is not None else int(plan.get("top_n", 100))
    rows = rows[:limit]

    node_names = list((plan.get("nodes") or {}).keys())
    measurement_names = list((plan.get("measurements") or {}).keys())
    parse_names = node_names + measurement_names
    fields = ["selection_rank", "point_index", "witness_rank", "ngspice_rc", "ngspice_elapsed_s"]
    for name in node_names:
        fields += [f"mlp_{name}_v", f"ng_{name}_v", f"delta_{name}_v"]
    fields += measurement_names
    if plan.get("power"):
        fields += ["power_w"]
    fields += [
        "max_abs_voltage_delta_v",
        "dc_validation_status",
        "ac_gain_db",
        "ac_bandwidth_3db_hz",
        "ac_phase_low_frequency_deg",
        "ac_ugb_hz",
        "ac_phase_at_ugb_deg",
        "ac_phase_margin_deg",
        "validation_status",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for selection_rank, row in enumerate(rows, 1):
            started = time.perf_counter()
            with tempfile.TemporaryDirectory(prefix="openams-witness-") as tempdir:
                temp = Path(tempdir)
                rendered_source = temp / source_netlist.name
                env = {key: float(value) for key, value in (plan.get("constants") or {}).items()}
                env.update({key: float(value) for key, value in row.items() if value not in ("", None) and _is_float(value)})
                bindings = plan.get("source_bindings") or {}
                source = _render_source(source_netlist, bindings, env, rendered_source) if bindings else source_netlist
                ac_path = temp / "ac.raw"
                deck_path = temp / "validation.spice"
                deck_path.write_text(_build_deck(plan, row, source, library, ac_path), encoding="utf-8")
                proc = subprocess.run([ngspice, "-b", str(deck_path)], text=True, capture_output=True)
                elapsed = time.perf_counter() - started
                parsed_values = _parse_tagged_values(proc.stdout + "\n" + proc.stderr, parse_names)
                nodes = {name: parsed_values[name] for name in node_names if name in parsed_values}
                measurements = {name: parsed_values[name] for name in measurement_names if name in parsed_values}
                ac_cfg = plan.get("ac") or {}
                ac_metrics = (
                    _parse_ac_raw(
                        ac_path,
                        ac_cfg.get("output", "v(out)"),
                        float(ac_cfg.get("transfer_sign", 1.0)),
                    )
                    if ac_cfg.get("enabled", False)
                    and proc.returncode == 0
                    else {}
                )

            record: dict[str, Any] = {
                "selection_rank": selection_rank,
                "point_index": row.get("point_index", ""),
                "witness_rank": row.get("witness_rank", ""),
                "ngspice_rc": proc.returncode,
                "ngspice_elapsed_s": elapsed,
            }
            deltas = []
            for name, spec in plan.get("nodes", {}).items():
                expected = _value(row, spec["witness_column"])
                actual = nodes.get(name, float("nan"))
                delta = actual - expected if np.isfinite(actual) else float("nan")
                record[f"mlp_{name}_v"] = expected
                record[f"ng_{name}_v"] = actual
                record[f"delta_{name}_v"] = delta
                if np.isfinite(delta):
                    deltas.append(abs(delta))
            for name, spec in (plan.get("measurements") or {}).items():
                value = measurements.get(name, float("nan"))
                if spec.get("absolute", False) and np.isfinite(value):
                    value = abs(value)
                record[name] = value

            power = plan.get("power") or {}
            if power:
                current_name = power["current_measurement"]
                current = record.get(current_name, float("nan"))
                supply_voltage = float(power.get("supply_voltage_v", 0.0))
                record["power_w"] = abs(supply_voltage) * abs(current) if np.isfinite(current) else float("nan")

            maximum = max(deltas) if deltas else float("nan")
            tolerance = float(plan.get("dc_tolerance_v", 0.05))
            dc_ok = proc.returncode == 0 and len(nodes) == len(node_names) and np.isfinite(maximum) and maximum <= tolerance
            record["max_abs_voltage_delta_v"] = maximum
            record["dc_validation_status"] = "PASS" if dc_ok else "FAIL"
            record.update(ac_metrics)
            ac_enabled = (plan.get("ac") or {}).get("enabled", False)
            ac_ok = (not ac_enabled) or bool(ac_metrics)
            record["validation_status"] = "PASS" if dc_ok and ac_ok else "FAIL"
            writer.writerow(record)
            stream.flush()
            print(f"[{selection_rank:3d}/{len(rows):3d}] point={row.get('point_index')} rc={proc.returncode} dc={record['dc_validation_status']} total={record['validation_status']}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Topology-generic ngspice validation of witness CSV rows.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--top-n", type=int)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--ngspice", default="ngspice")
    args = parser.parse_args()
    validate(args.plan, args.root, top_n=args.top_n, output_csv=args.output_csv, ngspice=args.ngspice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

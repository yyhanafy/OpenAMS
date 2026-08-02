"""Generic 100-case ngspice DC/AC validation.

This module:
- reads generic assignments,
- renders one ngspice deck per assignment,
- runs .op and .ac,
- parses gain, UGB, phase margin, and selected DC/device metrics,
- recovers table gm/gds values by technology-row provenance,
- estimates low-frequency gain from table gm/gds,
- writes CSV/JSON/Markdown evidence.

Important:
The current technology table supports gm/gds and low-frequency gain estimation.
UGB and phase margin are measured from ngspice only unless the technology source
contains explicit circuit-level prediction fields.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


class ValidationError(RuntimeError):
    pass


def num(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise ValidationError(f"{name} must be finite: {value!r}")
    return result


def load_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in ("", None):
            return row[name]
    raise KeyError(names)


def load_table(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def interpolate(lower: float, upper: float, fraction: float) -> float:
    return lower + fraction * (upper - lower)


def safe_rel_error(actual: float, reference: float) -> float | None:
    if not math.isfinite(actual) or not math.isfinite(reference):
        return None
    if abs(reference) < 1e-30:
        return None
    return abs(actual - reference) / abs(reference)



def load_yaml(path: Path) -> Mapping[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def nested_get(data: Mapping[str, Any], *paths: Sequence[str], default: Any = None) -> Any:
    for path in paths:
        current: Any = data
        try:
            for key in path:
                current = current[key]
            return current
        except (KeyError, TypeError):
            continue
    return default


PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render_template(template: str, values: Mapping[str, Any]) -> str:
    """Render OpenAMS brace placeholders and fail on unresolved tokens."""
    rendered = template

    # Replace longer brace forms first.
    for key, value in values.items():
        token_value = str(value)
        for token in (
            "{{" + key + "}}",
            "${" + key + "}",
            "@" + key + "@",
            "{" + key + "}",
        ):
            rendered = rendered.replace(token, token_value)

    unresolved = sorted(set(PLACEHOLDER_RE.findall(rendered)))
    if unresolved:
        raise ValidationError(
            "unresolved deck placeholders: " + ", ".join(unresolved)
        )
    return rendered


def metadata_template_values(
    *,
    repo_root: Path,
    input_dir: Path,
    model: Mapping[str, Any],
) -> dict[str, Any]:
    simulation = load_yaml(input_dir / "simulation.yaml")
    rules = load_yaml(input_dir / "design_rules.yaml")
    specs = load_yaml(input_dir / "specs.yaml")

    technology = model["technology"]
    pdk_library = nested_get(
        simulation,
        ("pdk", "library"),
        ("pdk", "library_path"),
        ("ngspice", "library"),
        default=None,
    )
    if not pdk_library:
        # The characterized technology CSV does not identify the PDK .lib.
        # Fall back to the user's established environment variable.
        import os
        pdk_library = os.environ.get("SKY130_LIB")

    if not pdk_library:
        raise ValidationError(
            "PDK library path not found in simulation.yaml and SKY130_LIB is unset"
        )

    pdk_library = str(Path(pdk_library).expanduser().resolve())
    source_netlist = (input_dir / "netlist.spice").resolve()

    operating = rules.get("operating_conditions", {})
    device_constraints = rules.get("device_constraints", {})
    all_mos = device_constraints.get("all_mos", device_constraints)

    values = {
        "pdk_library": pdk_library,
        "pdk_corner": nested_get(
            simulation,
            ("pdk", "corner"),
            default=technology.get("corner", "tt"),
        ),
        "temperature_c": nested_get(
            simulation,
            ("pdk", "temperature_c"),
            default=technology.get("temperature_c", 27.0),
        ),
        "source_netlist": str(source_netlist),
        "input_common_mode": operating.get(
            "vin_cm_v",
            nested_get(specs, ("conditions", "vin_cm_v"), default=0.9),
        ),
        "load_capacitance": operating.get(
            "c_load_f",
            nested_get(specs, ("conditions", "load_capacitance_f"), default=1e-11),
        ),
        "c_miller": operating.get("c_miller_f", 3e-12),
        "l_default": all_mos.get("length_um", 0.5) * 1e-6,
        "l_default_um": all_mos.get("length_um", 0.5),
        "analysis_block": "",
    }

    # Legacy aliases retained by the current deck template.
    values.update(
        {
            "w_input": 1.0,
            "w_load": 1.0,
            "w_tail": 1.0,
            "w_stage2": 1.0,
            "w_sink": 1.0,
        }
    )
    return values


def inject_control_block(
    deck: str,
    *,
    ac_start_hz: float,
    ac_stop_hz: float,
    points_per_decade: int,
    hierarchy_prefix: str = "xu1",
) -> str:
    """Insert one control block immediately before the final .end."""
    marker = "OPENAMS_GENERIC_VALIDATION_CONTROL"

    # Remove any previously appended validation block.
    marker_pos = deck.find("* " + marker)
    if marker_pos >= 0:
        deck = deck[:marker_pos].rstrip() + "\n"

    control_lines = [
        f"* {marker}",
        ".control",
        "set noaskquit",
        "set filetype=ascii",
        "op",
        "echo OPENAMS_OP_BEGIN",
        "print v(vtail) v(n1) v(n2) v(vbias) v(out)",
        "echo OPENAMS_OP_END",
        f"ac dec {points_per_decade} {ac_start_hz:.12g} {ac_stop_hz:.12g}",
        "wrdata openams_ac.dat frequency vdb(out) vp(out)",
        "echo OPENAMS_DEVICE_BEGIN",
    ]

    for idx in range(1, 8):
        instance = f"@m.{hierarchy_prefix}.xm{idx}"
        control_lines.append(
            f"show {instance}[gm] {instance}[gds] "
            f"{instance}[vds] {instance}[vdsat]"
        )

    control_lines.extend(
        [
            "echo OPENAMS_DEVICE_END",
            "quit",
            ".endc",
        ]
    )
    control = "\n".join(control_lines) + "\n"

    # Remove all terminal .end lines, then append one final .end.
    lines = deck.rstrip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()

    final_end_index = None
    for idx in range(len(lines) - 1, -1, -1):
        if re.match(r"^\s*\.end\s*$", lines[idx], re.IGNORECASE):
            final_end_index = idx
            break

    if final_end_index is None:
        body = "\n".join(lines).rstrip() + "\n"
    else:
        body = "\n".join(lines[:final_end_index]).rstrip() + "\n"

    return body + "\n" + control + ".end\n"



def assignment_to_template_values(row: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(row)

    for idx in range(1, 8):
        values.setdefault(f"w_m{idx}", row.get(f"w_m{idx}_um"))
        values.setdefault(f"w_m{idx}_um", row.get(f"w_m{idx}_um"))
        values.setdefault(f"nf_m{idx}", int(round(num(row[f"nf_m{idx}"], f"nf_m{idx}"))))
        values.setdefault(f"m{idx}_w_um", row.get(f"w_m{idx}_um"))
        values.setdefault(f"m{idx}_nf", values[f"nf_m{idx}"])

    aliases = {
        "vdd": "vdd_v",
        "vss": "vss_v",
        "vin_cm": "vin_cm_v",
        "vbias": "vbias_v",
        "vout": "vout_v",
        "vtail": "vtail_v",
        "n1": "n1_v",
        "n2": "n2_v",
    }
    for alias, source in aliases.items():
        if source in row:
            values.setdefault(alias, row[source])

    return values


def run_ngspice(
    deck_path: Path,
    case_dir: Path,
    repo_root: Path,
    timeout_s: int,
) -> tuple[int, str]:
    exe = shutil.which("ngspice")
    if not exe:
        raise ValidationError("ngspice executable not found on PATH")

    log_path = case_dir / "ngspice.log"
    completed = subprocess.run(
        [exe, "-b", "-o", str(log_path.resolve()), str(deck_path.resolve())],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_s,
        check=False,
    )
    log_text = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.exists()
        else completed.stdout
    )
    return completed.returncode, log_text


def parse_wrdata(path: Path) -> list[tuple[float, float, float]]:
    """Return (frequency_hz, gain_db, phase_deg)."""
    rows = []
    if not path.exists():
        return rows

    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            stripped = line.strip()
            if not stripped or stripped.startswith("*"):
                continue
            parts = stripped.split()
            try:
                numbers = [float(part) for part in parts]
            except ValueError:
                continue

            # wrdata may duplicate scale columns. Prefer the first frequency and
            # last two dependent values.
            if len(numbers) >= 3:
                frequency = numbers[0]
                gain_db = numbers[-2]
                phase_deg = numbers[-1]
                if frequency > 0 and all(math.isfinite(x) for x in (gain_db, phase_deg)):
                    rows.append((frequency, gain_db, phase_deg))
    return rows


def unwrap_phase_deg(phases: Sequence[float]) -> list[float]:
    if not phases:
        return []
    result = [phases[0]]
    for phase in phases[1:]:
        adjusted = phase
        while adjusted - result[-1] > 180:
            adjusted -= 360
        while adjusted - result[-1] < -180:
            adjusted += 360
        result.append(adjusted)
    return result


def interpolate_crossing(
    x0: float, y0: float, x1: float, y1: float, target: float
) -> float:
    if y1 == y0:
        return x0
    alpha = (target - y0) / (y1 - y0)
    return x0 + alpha * (x1 - x0)


def extract_ac_metrics(rows: Sequence[tuple[float, float, float]]) -> dict[str, Any]:
    if not rows:
        return {
            "gain_db": None,
            "ugb_hz": None,
            "phase_margin_deg": None,
            "ac_status": "NO_AC_DATA",
        }

    ordered = sorted(rows, key=lambda item: item[0])
    freqs = [row[0] for row in ordered]
    gains = [row[1] for row in ordered]
    phases = unwrap_phase_deg([row[2] for row in ordered])

    gain_db = gains[0]
    ugb = None
    phase_at_ugb = None

    for i in range(len(ordered) - 1):
        g0, g1 = gains[i], gains[i + 1]
        if (g0 >= 0 >= g1) or (g0 <= 0 <= g1):
            # Interpolate in log-frequency domain.
            lf0 = math.log10(freqs[i])
            lf1 = math.log10(freqs[i + 1])
            lfc = interpolate_crossing(lf0, g0, lf1, g1, 0.0)
            ugb = 10 ** lfc

            if g1 != g0:
                alpha = (0.0 - g0) / (g1 - g0)
            else:
                alpha = 0.0
            phase_at_ugb = phases[i] + alpha * (phases[i + 1] - phases[i])
            break

    pm = None
    if phase_at_ugb is not None:
        pm = 180.0 + phase_at_ugb
        while pm > 360:
            pm -= 360
        while pm < -180:
            pm += 360

    return {
        "gain_db": gain_db,
        "ugb_hz": ugb,
        "phase_margin_deg": pm,
        "ac_status": "PASS" if ugb is not None else "NO_0DB_CROSSING",
    }


DEVICE_VALUE_RE = re.compile(
    r"@m\.[^\[]*xm(?P<device>[1-7])\[(?P<metric>gm|gds|vds|vdsat)\]\s*=\s*(?P<value>[+\-0-9.eE]+)",
    re.IGNORECASE,
)


def parse_device_metrics(log_text: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for match in DEVICE_VALUE_RE.finditer(log_text):
        device = match.group("device")
        metric = match.group("metric").lower()
        result[f"{metric}_spice_m{device}"] = float(match.group("value"))
    return result


NODE_RE = re.compile(
    r"\b(v\(vtail\)|v\(n1\)|v\(n2\)|v\(vbias\)|v\(out\))\s*=\s*(?P<value>[+\-0-9.eE]+)",
    re.IGNORECASE,
)


def parse_node_metrics(log_text: str) -> dict[str, float]:
    mapping = {
        "v(vtail)": "vtail_spice_v",
        "v(n1)": "n1_spice_v",
        "v(n2)": "n2_spice_v",
        "v(vbias)": "vbias_spice_v",
        "v(out)": "vout_spice_v",
    }
    result = {}
    for match in NODE_RE.finditer(log_text):
        result[mapping[match.group(1).lower()]] = float(match.group("value"))
    return result


def table_device_metrics(
    assignment: Mapping[str, Any],
    table_rows: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}

    exact_devices = (1, 2, 3, 4, 5, 7)
    for idx in exact_devices:
        key = f"m{idx}_technology_row_index"
        if key not in assignment:
            continue
        row = table_rows[int(assignment[key])]
        for metric, fields in (
            ("gm", ("gm_s", "gm")),
            ("gds", ("gds_s", "gds")),
            ("vdsat", ("vdsat_abs_v", "vdsat_v")),
        ):
            try:
                out[f"{metric}_table_m{idx}"] = num(first(row, *fields), f"{metric} M{idx}")
            except KeyError:
                out[f"{metric}_table_m{idx}"] = None

    # M6 interpolation.
    lo_key = "m6_lower_technology_row_index"
    hi_key = "m6_upper_technology_row_index"
    alpha_key = "m6_interpolation_fraction"
    if all(key in assignment for key in (lo_key, hi_key, alpha_key)):
        lower = table_rows[int(assignment[lo_key])]
        upper = table_rows[int(assignment[hi_key])]
        alpha = num(assignment[alpha_key], alpha_key)
        for metric, fields in (
            ("gm", ("gm_s", "gm")),
            ("gds", ("gds_s", "gds")),
            ("vdsat", ("vdsat_abs_v", "vdsat_v")),
        ):
            try:
                lv = num(first(lower, *fields), f"{metric} M6 lower")
                uv = num(first(upper, *fields), f"{metric} M6 upper")
                out[f"{metric}_table_m6"] = interpolate(lv, uv, alpha)
            except KeyError:
                out[f"{metric}_table_m6"] = None

    return out


def estimate_low_frequency_gain_db(metrics: Mapping[str, Any]) -> float | None:
    """Approximate two-stage low-frequency gain from gm/gds.

    This is explicitly a validation estimate, not a replacement for AC simulation.
    """
    required = (
        "gm_table_m1",
        "gds_table_m1",
        "gds_table_m3",
        "gm_table_m6",
        "gds_table_m6",
        "gds_table_m7",
    )
    if any(metrics.get(name) in (None, 0) for name in required):
        return None

    gm1 = float(metrics["gm_table_m1"])
    ro1_inv = float(metrics["gds_table_m1"]) + float(metrics["gds_table_m3"])
    gm6 = float(metrics["gm_table_m6"])
    ro2_inv = float(metrics["gds_table_m6"]) + float(metrics["gds_table_m7"])

    if ro1_inv <= 0 or ro2_inv <= 0:
        return None

    gain_linear = (gm1 / ro1_inv) * (gm6 / ro2_inv)
    if gain_linear <= 0:
        return None
    return 20.0 * math.log10(gain_linear)


def compare_case(
    assignment: Mapping[str, Any],
    table_metrics: Mapping[str, Any],
    spice_metrics: Mapping[str, Any],
    ac_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    result = {
        "assignment_id": assignment["assignment_id"],
        **table_metrics,
        **spice_metrics,
        **ac_metrics,
    }

    predicted_gain = estimate_low_frequency_gain_db(table_metrics)
    result["gain_table_estimate_db"] = predicted_gain
    result["gain_error_db"] = (
        abs(float(ac_metrics["gain_db"]) - predicted_gain)
        if ac_metrics.get("gain_db") is not None and predicted_gain is not None
        else None
    )

    for idx in range(1, 8):
        for metric in ("gm", "gds"):
            table_key = f"{metric}_table_m{idx}"
            spice_key = f"{metric}_spice_m{idx}"
            error_key = f"{metric}_relative_error_m{idx}"
            if table_metrics.get(table_key) is not None and spice_metrics.get(spice_key) is not None:
                result[error_key] = safe_rel_error(
                    float(table_metrics[table_key]),
                    float(spice_metrics[spice_key]),
                )
            else:
                result[error_key] = None

    return result


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assignments",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/assignment_synthesis/"
            "generic_assignments_smoke.json"
        ),
    )
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/compiled_circuit_model.json"
        ),
    )
    parser.add_argument(
        "--deck-template",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/inputs/deck_template.spice"
        ),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/"
            "generic_ngspice_validation"
        ),
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--timeout-s", type=int, default=60)
    parser.add_argument("--ac-start-hz", type=float, default=1.0)
    parser.add_argument("--ac-stop-hz", type=float, default=1e10)
    parser.add_argument("--points-per-decade", type=int, default=100)
    args = parser.parse_args(argv)

    assignment_artifact = load_json(args.assignments)
    model = load_json(args.compiled_model)
    technology_path = Path(model["technology"]["source_path"]).resolve()
    table_rows = load_table(technology_path)

    assignments = list(assignment_artifact["assignments"])[: args.limit]
    if not assignments:
        raise ValidationError("assignment artifact contains no assignments")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = args.output_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path.cwd().resolve()
    template = args.deck_template.read_text(encoding="utf-8")
    static_values = metadata_template_values(
        repo_root=repo_root,
        input_dir=args.input_dir.resolve(),
        model=model,
    )
    results = []
    failure_counts: dict[str, int] = {}

    for case_index, assignment in enumerate(assignments, start=1):
        case_id = str(assignment["assignment_id"])
        case_dir = cases_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        values = {
            **static_values,
            **assignment_to_template_values(assignment),
        }
        deck = render_template(template, values)
        deck = inject_control_block(
            deck,
            ac_start_hz=args.ac_start_hz,
            ac_stop_hz=args.ac_stop_hz,
            points_per_decade=args.points_per_decade,
            hierarchy_prefix="xu1",
        )
        deck_path = case_dir / "validation.spice"
        deck_path.write_text(deck, encoding="utf-8")

        case_result: dict[str, Any] = {
            "assignment_id": case_id,
            "case_index": case_index,
            "deck_path": str(deck_path.resolve()),
            "technology_source": str(technology_path),
        }

        try:
            # Delete stale shared output before this case.
            shared_ac_path = repo_root / "openams_ac.dat"
            if shared_ac_path.exists():
                shared_ac_path.unlink()

            returncode, log_text = run_ngspice(
                deck_path,
                case_dir,
                repo_root,
                args.timeout_s,
            )

            case_ac_path = case_dir / "openams_ac.dat"
            if shared_ac_path.exists():
                shutil.move(str(shared_ac_path), str(case_ac_path))
            case_result["ngspice_returncode"] = returncode
            case_result["ngspice_status"] = "PASS" if returncode == 0 else "FAIL"

            device_spice = parse_device_metrics(log_text)
            node_spice = parse_node_metrics(log_text)
            ac_data = parse_wrdata(case_dir / "openams_ac.dat")
            ac_metrics = extract_ac_metrics(ac_data)
            table_metrics = table_device_metrics(assignment, table_rows)

            case_result.update(
                compare_case(
                    assignment,
                    table_metrics,
                    {**device_spice, **node_spice},
                    ac_metrics,
                )
            )

            if returncode != 0:
                status = "NGSPICE_FAILURE"
            elif ac_metrics["gain_db"] is None:
                status = "AC_EXTRACTION_FAILURE"
            else:
                status = "PASS"

            case_result["status"] = status

        except subprocess.TimeoutExpired:
            case_result["status"] = "TIMEOUT"
            case_result["ngspice_status"] = "TIMEOUT"
        except Exception as exc:
            case_result["status"] = "ERROR"
            case_result["error"] = f"{type(exc).__name__}: {exc}"

        failure_counts[case_result["status"]] = failure_counts.get(case_result["status"], 0) + 1
        results.append(case_result)

        print(
            f"[{case_index:03d}/{len(assignments):03d}] "
            f"{case_id}: {case_result['status']}",
            flush=True,
        )

    results_csv = args.output_dir / "generic_100_case_results.csv"
    results_json = args.output_dir / "generic_100_case_results.json"
    report_md = args.output_dir / "GENERIC_100_CASE_VALIDATION_REPORT.md"

    write_csv(results_csv, results)

    summary = {
        "artifact": "openams.generic_100_case_ngspice_ac_validation",
        "schema_version": 1,
        "assignment_source": str(args.assignments.resolve()),
        "compiled_model": str(args.compiled_model.resolve()),
        "technology_source": str(technology_path),
        "deck_template": str(args.deck_template.resolve()),
        "cases_requested": args.limit,
        "cases_processed": len(results),
        "status_counts": failure_counts,
        "results": results,
        "limitations": [
            "Technology-table UGB prediction is unavailable unless capacitance or circuit-level AC fields exist.",
            "Technology-table phase-margin prediction is unavailable unless capacitance or circuit-level AC fields exist.",
            "gain_table_estimate_db is an analytical gm/gds estimate, not a full AC solution.",
        ],
    }
    results_json.write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    passed = failure_counts.get("PASS", 0)
    gain_pairs = [
        row for row in results
        if row.get("gain_db") is not None
        and row.get("gain_table_estimate_db") is not None
    ]
    mean_gain_error = (
        sum(float(row["gain_error_db"]) for row in gain_pairs)
        / len(gain_pairs)
        if gain_pairs
        else None
    )

    report = f"""# Generic 100-Case ngspice AC Validation

## Summary

- Cases processed: {len(results)}
- PASS: {passed}
- Status counts: `{json.dumps(failure_counts, sort_keys=True)}`
- Mean absolute gain error, table estimate vs ngspice: {mean_gain_error if mean_gain_error is not None else "N/A"} dB

## Compared Metrics

### Technology table versus ngspice

- Device `gm`
- Device `gds`
- Low-frequency gain estimate derived from table `gm/gds`

### ngspice measured

- DC operating point
- Low-frequency gain
- Unity-gain bandwidth
- Phase margin

## Important Limitation

The current technology table does not provide sufficient capacitance data or
explicit circuit-level AC predictions to calculate trustworthy lookup-derived
UGB and phase margin. Therefore, UGB and phase margin are extracted from ngspice
and reported, but not falsely compared against invented lookup values.

## Artifacts

- `{results_csv}`
- `{results_json}`
- `{cases_dir}`
"""
    report_md.write_text(report, encoding="utf-8")

    print()
    print("===== GENERIC 100-CASE VALIDATION COMPLETE =====")
    print(f"cases processed: {len(results)}")
    print(f"status counts:   {failure_counts}")
    print(f"csv:             {results_csv}")
    print(f"json:            {results_json}")
    print(f"report:          {report_md}")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

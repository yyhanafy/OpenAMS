\
#!/usr/bin/env python3
"""Extract and compare ngspice AC metrics for OpenAMS validation points.\n\nV5 can execute ngspice directly and records deck/output hashes, timestamps, freshness, and runtime provenance.

Inputs:
- point directories produced by build_validation_decks.py
- per-point validation_result.json produced by run_ngspice_dc_validation.py
- per-point assignment.json containing frozen OpenAMS AC estimates
- per-point openams_ac.dat produced by ngspice

Outputs:
- per-point ac_metrics.json
- aggregate_ac_comparison.csv
- ac_validation_summary.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--include-dc-ineligible",
        action="store_true",
        help="Process points even when validation_result.json has proceed_to_ac=false.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output and per-point ac_metrics.json files.",
    )
    parser.add_argument(
        "--run-ngspice",
        action="store_true",
        help="Run ngspice for each AC-eligible point before parsing results.",
    )
    parser.add_argument(
        "--ngspice",
        default="ngspice",
        help="ngspice executable (default: ngspice).",
    )
    parser.add_argument(
        "--require-fresh-ac",
        action="store_true",
        help="Require openams_ac.dat to be newer than deck.spice.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_ngspice(point_dir: Path, executable: str) -> dict[str, Any]:
    deck_path = point_dir / "deck.spice"
    log_path = point_dir / "ngspice.log"
    ac_path = point_dir / "openams_ac.dat"

    before_ns = time.time_ns()
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()

    proc = subprocess.run(
        [executable, "-b", "-o", "ngspice.log", "deck.spice"],
        cwd=point_dir,
        text=True,
        capture_output=True,
    )

    runtime_s = time.perf_counter() - start
    finished_at = datetime.now(timezone.utc).isoformat()

    ac_exists = ac_path.is_file()
    ac_mtime_ns = ac_path.stat().st_mtime_ns if ac_exists else None
    generated_fresh = bool(ac_exists and ac_mtime_ns is not None and ac_mtime_ns >= before_ns)

    return {
        "executed": True,
        "command": [executable, "-b", "-o", "ngspice.log", "deck.spice"],
        "return_code": proc.returncode,
        "runtime_s": runtime_s,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "log_path": str(log_path),
        "ac_path": str(ac_path),
        "ac_exists": ac_exists,
        "ac_generated_fresh": generated_fresh,
    }


def finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def normalize_phase_deg(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def read_ac_table(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows: list[tuple[float, float, float]] = []

    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("*"):
            continue

        tokens = line.replace(",", " ").split()
        numbers: list[float] = []
        for token in tokens:
            try:
                numbers.append(float(token))
            except ValueError:
                continue

        if len(numbers) < 3:
            continue

        # For:
        #   wrdata openams_ac.dat frequency vdb(out) vp(out)
        # ngspice-43 writes seven numeric columns:
        #
        #   1 scale(frequency)
        #   2 real(frequency)
        #   3 imag(frequency)
        #   4 scale(vdb(out))
        #   5 vdb(out) in dB
        #   6 scale(vp(out))
        #   7 vp(out) in radians
        #
        # Also support the compact four-column form produced by:
        #   wrdata openams_ac.dat vdb(out) vp(out)
        # where the layout is:
        #   frequency, gain_db, frequency, phase_radians
        if len(numbers) >= 7:
            frequency = numbers[0]
            gain_db = numbers[4]
            phase_deg = math.degrees(numbers[6])
        elif len(numbers) >= 4:
            frequency = numbers[0]
            gain_db = numbers[1]
            phase_deg = math.degrees(numbers[3])
        elif len(numbers) >= 3:
            frequency, gain_db, phase_deg = numbers[:3]
        else:
            continue

        if (
            math.isfinite(frequency)
            and math.isfinite(gain_db)
            and math.isfinite(phase_deg)
            and frequency > 0.0
        ):
            rows.append((frequency, gain_db, phase_deg))

    if len(rows) < 2:
        raise ValueError(f"Could not parse at least two AC rows from {path}")

    rows.sort(key=lambda item: item[0])
    array = np.asarray(rows, dtype=float)

    frequency = array[:, 0]
    gain_db = array[:, 1]
    phase_deg = array[:, 2]

    unique = np.concatenate(([True], np.diff(frequency) > 0.0))
    return frequency[unique], gain_db[unique], phase_deg[unique]


def interpolate_log_frequency(
    f1: float,
    f2: float,
    y1: float,
    y2: float,
    target: float,
) -> float:
    if y2 == y1:
        return math.sqrt(f1 * f2)

    fraction = (target - y1) / (y2 - y1)
    log_f = math.log10(f1) + fraction * (math.log10(f2) - math.log10(f1))
    return 10.0 ** log_f


def interpolate_value_log_frequency(
    frequency: float,
    f1: float,
    f2: float,
    y1: float,
    y2: float,
) -> float:
    if f2 == f1:
        return y1

    denominator = math.log10(f2) - math.log10(f1)
    if denominator == 0.0:
        return y1

    fraction = (math.log10(frequency) - math.log10(f1)) / denominator
    return y1 + fraction * (y2 - y1)


def extract_ac_metrics(
    frequency: np.ndarray,
    gain_db: np.ndarray,
    phase_raw_deg: np.ndarray,
) -> dict[str, Any]:
    gain_linear = np.power(10.0, gain_db / 20.0)

    low_frequency_gain_db = float(gain_db[0])
    low_frequency_gain_v_v = float(gain_linear[0])

    # The measured differential transfer is inverting, so its low-frequency
    # phase is near +180 degrees. Track the absolute phase continuously, then
    # measure the additional lag from that low-frequency inversion.
    #
    # Example:
    #   low-frequency phase  = +180 deg
    #   phase at unity gain  =  -30 deg
    #   additional phase lag = -210 deg
    #   signed phase margin  = 180 + (-210) = -30 deg
    #
    # A negative result is meaningful: it predicts instability under ideal
    # unity feedback. Do not take an absolute value or wrap it into 0..360.
    low_frequency_phase_deg = float(phase_raw_deg[0])
    absolute_phase_unwrapped_deg = np.rad2deg(
        np.unwrap(np.deg2rad(phase_raw_deg))
    )
    phase_unwrapped_deg = (
        absolute_phase_unwrapped_deg - absolute_phase_unwrapped_deg[0]
    )

    crossing_index: int | None = None
    for idx in range(len(gain_db) - 1):
        if gain_db[idx] >= 0.0 and gain_db[idx + 1] <= 0.0:
            crossing_index = idx
            break

    if crossing_index is None:
        return {
            "status": "NO_UNITY_GAIN_CROSSING",
            "gain_db": low_frequency_gain_db,
            "gain_v_v": low_frequency_gain_v_v,
            "ugb_hz": None,
            "low_frequency_phase_absolute_deg": float(phase_raw_deg[0]),
            "phase_at_ugb_unwrapped_deg": None,
            "phase_at_ugb_deg": None,
            "phase_margin_deg": None,
            "frequency_start_hz": float(frequency[0]),
            "frequency_stop_hz": float(frequency[-1]),
            "ac_rows": int(len(frequency)),
        }

    idx = crossing_index
    ugb_hz = interpolate_log_frequency(
        float(frequency[idx]),
        float(frequency[idx + 1]),
        float(gain_db[idx]),
        float(gain_db[idx + 1]),
        0.0,
    )

    phase_at_ugb_unwrapped_deg = interpolate_value_log_frequency(
        ugb_hz,
        float(frequency[idx]),
        float(frequency[idx + 1]),
        float(phase_unwrapped_deg[idx]),
        float(phase_unwrapped_deg[idx + 1]),
    )
    # Keep both the relative lag and the signed margin unwrapped.
    phase_at_ugb_deg = phase_at_ugb_unwrapped_deg
    phase_margin_deg = 180.0 + phase_at_ugb_unwrapped_deg

    return {
        "status": "PASS",
        "gain_db": low_frequency_gain_db,
        "gain_v_v": low_frequency_gain_v_v,
        "ugb_hz": ugb_hz,
        "low_frequency_phase_absolute_deg": low_frequency_phase_deg,
        "phase_at_ugb_unwrapped_deg": phase_at_ugb_unwrapped_deg,
        "phase_at_ugb_deg": phase_at_ugb_deg,
        "phase_margin_deg": phase_margin_deg,
        "frequency_start_hz": float(frequency[0]),
        "frequency_stop_hz": float(frequency[-1]),
        "ac_rows": int(len(frequency)),
    }


def find_nested_value(data: Any, candidate_keys: tuple[str, ...]) -> float | None:
    if isinstance(data, dict):
        for key in candidate_keys:
            if key in data:
                value = finite(data[key])
                if value is not None:
                    return value
        for value in data.values():
            found = find_nested_value(value, candidate_keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_nested_value(value, candidate_keys)
            if found is not None:
                return found
    return None


def expected_ac_metrics(assignment_record: dict[str, Any]) -> dict[str, float | None]:
    return {
        "gain_db": find_nested_value(
            assignment_record,
            ("gain_est_db", "gain_db"),
        ),
        "gain_v_v": find_nested_value(
            assignment_record,
            ("gain_est_v_v", "gain_v_v"),
        ),
        "ugb_hz": find_nested_value(
            assignment_record,
            ("ugb_est_hz", "ugb_hz"),
        ),
        "phase_at_ugb_unwrapped_deg": find_nested_value(
            assignment_record,
            (
                "phase_at_ugb_unwrapped_est_deg",
                "phase_at_ugb_unwrapped_deg",
            ),
        ),
        "phase_at_ugb_deg": find_nested_value(
            assignment_record,
            ("phase_at_ugb_est_deg", "phase_at_ugb_deg"),
        ),
        "phase_margin_deg": find_nested_value(
            assignment_record,
            ("phase_margin_est_deg", "phase_margin_deg"),
        ),
    }


def comparison(actual: float | None, expected: float | None) -> dict[str, float | None]:
    if actual is None or expected is None:
        return {
            "expected": expected,
            "actual": actual,
            "signed_error": None,
            "absolute_error": None,
            "relative_error": None,
        }

    signed_error = actual - expected
    absolute_error = abs(signed_error)
    relative_error = (
        absolute_error / abs(expected)
        if expected != 0.0
        else None
    )
    return {
        "expected": expected,
        "actual": actual,
        "signed_error": signed_error,
        "absolute_error": absolute_error,
        "relative_error": relative_error,
    }


def point_dirs(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.glob("point_*")
        if path.is_dir()
        and (path / "assignment.json").is_file()
        and (path / "openams_ac.dat").is_file()
    )


def correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if np.std(x) == 0.0 or np.std(y) == 0.0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def ranks(values: list[float]) -> list[float]:
    order = np.argsort(values)
    ranked = np.empty(len(values), dtype=float)
    ranked[order] = np.arange(len(values), dtype=float)
    return ranked.tolist()


def summarize_metric(
    rows: list[dict[str, Any]],
    expected_key: str,
    actual_key: str,
) -> dict[str, Any]:
    pairs = [
        (float(row[expected_key]), float(row[actual_key]))
        for row in rows
        if row.get(expected_key) not in (None, "")
        and row.get(actual_key) not in (None, "")
    ]

    if not pairs:
        return {
            "count": 0,
            "pearson": None,
            "spearman": None,
            "median_absolute_error": None,
            "p95_absolute_error": None,
        }

    expected = [pair[0] for pair in pairs]
    actual = [pair[1] for pair in pairs]
    absolute_errors = np.abs(np.asarray(actual) - np.asarray(expected))

    return {
        "count": len(pairs),
        "pearson": correlation(expected, actual),
        "spearman": correlation(ranks(expected), ranks(actual)),
        "median_absolute_error": float(np.median(absolute_errors)),
        "p95_absolute_error": float(np.percentile(absolute_errors, 95)),
        "mean_signed_error": float(np.mean(np.asarray(actual) - np.asarray(expected))),
    }


def main() -> int:
    args = parse_args()
    points_root = args.points.resolve()
    output = args.output.resolve()

    dirs = point_dirs(points_root)
    if args.limit is not None:
        dirs = dirs[: args.limit]

    if not dirs:
        raise FileNotFoundError(
            f"No point directories with assignment.json and openams_ac.dat under {points_root}"
        )

    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Output already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    skipped = 0

    for index, point_dir in enumerate(dirs, 1):
        dc_result_path = point_dir / "validation_result.json"
        if dc_result_path.is_file():
            dc_result = load_json(dc_result_path)
            proceed_to_ac = bool(dc_result.get("proceed_to_ac", False))
        else:
            dc_result = {}
            proceed_to_ac = args.include_dc_ineligible

        if not proceed_to_ac and not args.include_dc_ineligible:
            skipped += 1
            print(f"[{index}/{len(dirs)}] {point_dir.name} skipped: DC-ineligible")
            continue

        deck_path = point_dir / "deck.spice"
        ac_path = point_dir / "openams_ac.dat"
        log_path = point_dir / "ngspice.log"

        if args.run_ngspice:
            simulation = run_ngspice(point_dir, args.ngspice)
            if simulation["return_code"] != 0:
                raise RuntimeError(
                    f"ngspice failed for {point_dir.name} with return code "
                    f"{simulation['return_code']}"
                )
            if not simulation["ac_exists"]:
                raise FileNotFoundError(
                    f"ngspice did not create {ac_path}"
                )
            if not simulation["ac_generated_fresh"]:
                raise RuntimeError(
                    f"AC output was not freshly generated for {point_dir.name}"
                )
        else:
            simulation = {
                "executed": False,
                "command": None,
                "return_code": None,
                "runtime_s": None,
                "started_at_utc": None,
                "finished_at_utc": None,
                "stdout": None,
                "stderr": None,
                "log_path": str(log_path),
                "ac_path": str(ac_path),
                "ac_exists": ac_path.is_file(),
                "ac_generated_fresh": None,
            }

        if not ac_path.is_file():
            raise FileNotFoundError(f"Missing AC output: {ac_path}")

        deck_mtime_ns = deck_path.stat().st_mtime_ns
        ac_mtime_ns = ac_path.stat().st_mtime_ns
        ac_newer_than_deck = ac_mtime_ns >= deck_mtime_ns

        if args.require_fresh_ac and not ac_newer_than_deck:
            raise RuntimeError(
                f"Stale AC output for {point_dir.name}: "
                f"{ac_path.name} is older than deck.spice"
            )

        assignment_record = load_json(point_dir / "assignment.json")
        expected = expected_ac_metrics(assignment_record)

        frequency, gain_db, phase_deg = read_ac_table(ac_path)
        actual = extract_ac_metrics(frequency, gain_db, phase_deg)

        metric_comparisons = {
            "gain_db": comparison(actual.get("gain_db"), expected.get("gain_db")),
            "gain_v_v": comparison(actual.get("gain_v_v"), expected.get("gain_v_v")),
            "ugb_hz": comparison(actual.get("ugb_hz"), expected.get("ugb_hz")),
            "phase_at_ugb_unwrapped_deg": comparison(
                actual.get("phase_at_ugb_unwrapped_deg"),
                expected.get("phase_at_ugb_unwrapped_deg"),
            ),
            "phase_at_ugb_deg": comparison(
                actual.get("phase_at_ugb_deg"),
                expected.get("phase_at_ugb_deg"),
            ),
            "phase_margin_deg": comparison(
                actual.get("phase_margin_deg"),
                expected.get("phase_margin_deg"),
            ),
        }

        payload = {
            "grid_index": assignment_record.get("grid_index"),
            "assignment_id": assignment_record.get("assignment_id"),
            "point_directory": str(point_dir),
            "dc_classification": dc_result.get("classification"),
            "dc_physical_valid": dc_result.get("dc_physical_valid"),
            "proceed_to_ac": proceed_to_ac,
            "simulation_provenance": {
                **simulation,
                "deck_sha256": sha256_file(deck_path),
                "deck_mtime_ns": deck_mtime_ns,
                "ngspice_log_sha256": (
                    sha256_file(log_path) if log_path.is_file() else None
                ),
                "openams_ac_sha256": sha256_file(ac_path),
                "openams_ac_mtime_ns": ac_mtime_ns,
                "openams_ac_newer_than_deck": ac_newer_than_deck,
            },
            "ngspice_ac_metrics": actual,
            "openams_estimated_ac_metrics": expected,
            "comparisons": metric_comparisons,
        }

        ac_json = point_dir / "ac_metrics.json"
        if ac_json.exists() and not args.overwrite:
            raise FileExistsError(f"Per-point output already exists: {ac_json}")
        ac_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

        provenance = payload["simulation_provenance"]

        row: dict[str, Any] = {
            "grid_index": payload["grid_index"],
            "assignment_id": payload["assignment_id"],
            "dc_classification": payload["dc_classification"],
            "dc_physical_valid": payload["dc_physical_valid"],
            "proceed_to_ac": proceed_to_ac,
            "ngspice_executed_by_ac_validator": provenance["executed"],
            "ngspice_return_code": provenance["return_code"],
            "ngspice_runtime_s": provenance["runtime_s"],
            "deck_sha256": provenance["deck_sha256"],
            "openams_ac_sha256": provenance["openams_ac_sha256"],
            "openams_ac_newer_than_deck": provenance["openams_ac_newer_than_deck"],
            "ac_status": actual.get("status"),
            "ac_rows": actual.get("ac_rows"),
            "frequency_start_hz": actual.get("frequency_start_hz"),
            "frequency_stop_hz": actual.get("frequency_stop_hz"),
        }

        for name, values in metric_comparisons.items():
            row[f"{name}_openams"] = values["expected"]
            row[f"{name}_ngspice"] = values["actual"]
            row[f"{name}_signed_error"] = values["signed_error"]
            row[f"{name}_absolute_error"] = values["absolute_error"]
            row[f"{name}_relative_error"] = values["relative_error"]

        rows.append(row)

        print(
            f"[{index}/{len(dirs)}] {point_dir.name} "
            f"status={actual.get('status')} "
            f"gain_db={actual.get('gain_db')} "
            f"ugb_hz={actual.get('ugb_hz')} "
            f"pm_deg={actual.get('phase_margin_deg')}"
        )

    if not rows:
        raise RuntimeError("No AC-eligible points were processed")

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "status": "PASS",
        "points_discovered": len(dirs),
        "points_processed": len(rows),
        "points_skipped_dc_ineligible": skipped,
        "points_with_unity_gain_crossing": sum(
            row["ac_status"] == "PASS" for row in rows
        ),
        "ngspice_executed_by_ac_validator": args.run_ngspice,
        "require_fresh_ac": args.require_fresh_ac,
        "points_with_ac_newer_than_deck": sum(
            bool(row["openams_ac_newer_than_deck"]) for row in rows
        ),
        "aggregate_csv": str(output),
        "metrics": {
            "gain_db": summarize_metric(
                rows, "gain_db_openams", "gain_db_ngspice"
            ),
            "ugb_hz": summarize_metric(
                rows, "ugb_hz_openams", "ugb_hz_ngspice"
            ),
            "phase_margin_deg": summarize_metric(
                rows,
                "phase_margin_deg_openams",
                "phase_margin_deg_ngspice",
            ),
        },
    }

    summary_path = output.parent / "ac_validation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print("===== OPENAMS NGSPICE AC VALIDATION =====")
    print(f"points processed: {len(rows)}")
    print(f"points skipped:   {skipped}")
    print(f"aggregate CSV:    {output}")
    print(f"summary JSON:     {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

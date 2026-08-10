#!/usr/bin/env python3
"""
Generate a dense SKY130 MOS DC + small-signal characterization dataset.

The output preserves the legacy OpenAMS columns:
    polarity, model, corner, temperature_c, length_um, width_um,
    vgs_abs_v, vds_abs_v, vbs_abs_v, id_abs_a, vdsat_abs_v,
    vth_abs_v, gm_s, gds_s, saturated

and adds:
    gmb_s, terminal charges, the intrinsic capacitance matrix,
    derived gm/Id, ro, intrinsic gain, ft estimate, and normalized values.

The script characterizes the SKY130 1.8-V NMOS and PMOS subcircuits using
ngspice operating-point quantities. It processes independent devices in
batches, supports multiprocessing, checkpoint/resume, and writes a metadata
JSON beside the CSV.

Recommended first actions:
    1. Run --probe-only to verify the installed PDK/ngspice vector names.
    2. Run --profile smoke.
    3. Run --profile dense after inspecting the smoke output.

Example:
    export SKY130_LIB="$HOME/pdks/open_pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice"

    python tools/technology/characterize_sky130_mlp_dataset.py \
        --library "$SKY130_LIB" \
        --corner tt \
        --temperature-c 27 \
        --profile smoke \
        --output technology/sky130_tt_27c_mlp_smoke.csv \
        --probe-only

    python tools/technology/characterize_sky130_mlp_dataset.py \
        --library "$SKY130_LIB" \
        --corner tt \
        --temperature-c 27 \
        --profile dense \
        --workers 12 \
        --batch-size 128 \
        --output technology/sky130_tt_27c_mlp_dense.csv \
        --resume
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence


LEGACY_COLUMNS = [
    "polarity",
    "model",
    "corner",
    "temperature_c",
    "length_um",
    "width_um",
    "vgs_abs_v",
    "vds_abs_v",
    "vbs_abs_v",
    "id_abs_a",
    "vdsat_abs_v",
    "vth_abs_v",
    "gm_s",
    "gds_s",
    "saturated",
]

ADDED_RAW_COLUMNS = [
    "gmb_s",
    "qg_c",
    "qd_c",
    "qs_c",
    "qb_c",
    "cgg_f",
    "cgd_f",
    "cgs_f",
    "cgb_f",
    "cdg_f",
    "cdd_f",
    "cds_f",
    "cdb_f",
    "csg_f",
    "csd_f",
    "css_f",
    "csb_f",
    "cbg_f",
    "cbd_f",
    "cbs_f",
    "cbb_f",
]

DERIVED_COLUMNS = [
    "gm_over_id_1_v",
    "ro_ohm",
    "intrinsic_gain_v_v",
    "intrinsic_gain_db",
    "cgg_total_f",
    "ft_est_hz",
    "id_per_width_a_per_um",
    "gm_per_width_s_per_um",
    "gds_per_width_s_per_um",
    "simulation_valid",
    "missing_metric_count",
]

OUTPUT_COLUMNS = LEGACY_COLUMNS + ADDED_RAW_COLUMNS + DERIVED_COLUMNS

MODEL_BY_POLARITY = {
    "nmos": "sky130_fd_pr__nfet_01v8",
    "pmos": "sky130_fd_pr__pfet_01v8",
}

# ngspice/BSIM operating-point names. The CSV names remain stable even if
# a PDK or ngspice version uses one of the alternate vector names below.
VECTOR_CANDIDATES = {
    "id_abs_a": ("id",),
    "vdsat_abs_v": ("vdsat",),
    "vth_abs_v": ("vth", "von"),
    "gm_s": ("gm",),
    "gds_s": ("gds",),
    "gmb_s": ("gmbs", "gmb"),
    "qg_c": ("qg",),
    "qd_c": ("qd",),
    "qs_c": ("qs",),
    "qb_c": ("qb",),
    "cgg_f": ("cgg", "cggb"),
    "cgd_f": ("cgd", "cgdb"),
    "cgs_f": ("cgs", "cgsb"),
    "cgb_f": ("cgb", "cgbb"),
    "cdg_f": ("cdg", "cdgb"),
    "cdd_f": ("cdd", "cddb"),
    "cds_f": ("cds", "cdsb"),
    "cdb_f": ("cdb", "cdbb"),
    "csg_f": ("csg", "csgb"),
    "csd_f": ("csd", "csdb"),
    "css_f": ("css", "cssb"),
    "csb_f": ("csb", "csbb"),
    "cbg_f": ("cbg", "cbgb"),
    "cbd_f": ("cbd", "cbdb"),
    "cbs_f": ("cbs", "cbsb"),
    "cbb_f": ("cbb", "cbbb"),
}

REQUIRED_METRICS = {
    "id_abs_a",
    "vdsat_abs_v",
    "vth_abs_v",
    "gm_s",
    "gds_s",
    "gmb_s",
    "cgg_f",
    "cgd_f",
    "cgs_f",
    "cgb_f",
    "cdd_f",
    "cdb_f",
}


@dataclass(frozen=True)
class BiasPoint:
    polarity: str
    length_um: float
    width_um: float
    vgs_abs_v: float
    vds_abs_v: float
    vbs_abs_v: float


@dataclass(frozen=True)
class BatchJob:
    job_id: int
    points: tuple[BiasPoint, ...]
    library: str
    corner: str
    temperature_c: float
    ngspice: str
    sat_margin_v: float
    timeout_s: float
    keep_decks_dir: str | None
    allow_missing_metrics: bool


def unique_sorted(values: Iterable[float], digits: int = 12) -> list[float]:
    return sorted({round(float(v), digits) for v in values})


def inclusive_range(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    count = int(math.floor((stop - start) / step + 1e-9))
    values = [start + i * step for i in range(count + 1)]
    if not math.isclose(values[-1], stop, rel_tol=0.0, abs_tol=1e-10):
        values.append(stop)
    return unique_sorted(values)


def piecewise_grid(segments: Sequence[tuple[float, float, float]]) -> list[float]:
    values: list[float] = []
    for start, stop, step in segments:
        values.extend(inclusive_range(start, stop, step))
    return unique_sorted(values)


def parse_number_list(text: str) -> list[float]:
    """
    Parse comma-separated values and ranges.

    Accepted tokens:
        0.42,1,2,4
        0.0:0.2:0.01
        0.3:0.8:0.025
    """
    values: list[float] = []
    for raw_token in text.split(","):
        token = raw_token.strip()
        if not token:
            continue
        parts = token.split(":")
        if len(parts) == 1:
            values.append(float(parts[0]))
        elif len(parts) == 3:
            values.extend(inclusive_range(*(float(p) for p in parts)))
        else:
            raise ValueError(f"Invalid grid token: {token!r}")
    if not values:
        raise ValueError("Grid may not be empty")
    return unique_sorted(values)


def profile_grids(profile: str) -> dict[str, list[float]]:
    if profile == "smoke":
        return {
            "lengths_um": [0.5],
            "widths_um": [0.42, 1.0, 2.0, 4.0, 8.0, 16.0],
            "vgs_v": [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.8],
            "vds_v": [0.01, 0.05, 0.15, 0.3, 0.6, 1.0, 1.5, 1.8],
            "vbs_v": [0.0, 0.1, 0.2, 0.3],
        }

    if profile == "dense":
        return {
            "lengths_um": [0.5],
            "widths_um": [
                0.42, 0.5, 0.63, 0.8, 1.0, 1.25, 1.6, 2.0, 2.5,
                3.2, 4.0, 5.0, 6.3, 8.0, 10.0, 12.5, 16.0, 20.0,
                25.0, 32.0, 40.0, 50.0, 63.0, 80.0, 100.0,
            ],
            # Fine around threshold/moderate inversion.
            "vgs_v": piecewise_grid([
                (0.00, 0.30, 0.05),
                (0.30, 0.80, 0.01),
                (0.80, 1.30, 0.025),
                (1.30, 1.80, 0.05),
            ]),
            # Fine near zero and the triode/saturation transition.
            "vds_v": piecewise_grid([
                (0.01, 0.20, 0.01),
                (0.20, 0.80, 0.025),
                (0.80, 1.80, 0.05),
            ]),
            "vbs_v": inclusive_range(0.0, 0.3, 0.025),
        }

    if profile == "technology":
        # Broader length coverage, but a somewhat reduced voltage grid to avoid
        # multiplying the densest fixed-L dataset by every length.
        return {
            "lengths_um": [0.15, 0.18, 0.25, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0],
            "widths_um": [
                0.42, 0.5, 0.63, 0.8, 1.0, 1.25, 1.6, 2.0, 2.5,
                3.2, 4.0, 5.0, 6.3, 8.0, 10.0, 12.5, 16.0, 20.0,
                25.0, 32.0, 40.0, 50.0, 63.0, 80.0, 100.0,
            ],
            "vgs_v": piecewise_grid([
                (0.00, 0.30, 0.05),
                (0.30, 0.90, 0.025),
                (0.90, 1.80, 0.05),
            ]),
            "vds_v": piecewise_grid([
                (0.01, 0.20, 0.02),
                (0.20, 0.80, 0.05),
                (0.80, 1.80, 0.10),
            ]),
            "vbs_v": inclusive_range(0.0, 0.3, 0.05),
        }

    raise ValueError(f"Unknown profile: {profile}")


def chunked(items: Iterable[BiasPoint], size: int) -> Iterator[tuple[BiasPoint, ...]]:
    if size <= 0:
        raise ValueError("batch size must be positive")
    batch: list[BiasPoint] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield tuple(batch)
            batch = []
    if batch:
        yield tuple(batch)


def point_key(point: BiasPoint) -> tuple[str, float, float, float, float, float]:
    return (
        point.polarity,
        point.length_um,
        point.width_um,
        point.vgs_abs_v,
        point.vds_abs_v,
        point.vbs_abs_v,
    )


def row_key(row: dict[str, str]) -> tuple[str, float, float, float, float, float]:
    return (
        row["polarity"],
        float(row["length_um"]),
        float(row["width_um"]),
        float(row["vgs_abs_v"]),
        float(row["vds_abs_v"]),
        float(row["vbs_abs_v"]),
    )


def generate_points(
    polarities: Sequence[str],
    lengths_um: Sequence[float],
    widths_um: Sequence[float],
    vgs_v: Sequence[float],
    vds_v: Sequence[float],
    vbs_v: Sequence[float],
    completed: set[tuple[str, float, float, float, float, float]],
) -> Iterator[BiasPoint]:
    for values in itertools.product(
        polarities, lengths_um, widths_um, vgs_v, vds_v, vbs_v
    ):
        point = BiasPoint(*values)
        if point_key(point) not in completed:
            yield point


def safe_instance_name(index: int) -> str:
    return f"xdut{index:04d}"


def internal_mos_path(instance_name: str, model: str) -> str:
    """
    SKY130 primitive path used by the open_pdks ngspice subcircuit.

    Example:
        @m.xdut0000.msky130_fd_pr__nfet_01v8[gm]
    """
    return f"@m.{instance_name}.m{model}"


def build_device_lines(point: BiasPoint, index: int) -> list[str]:
    xname = safe_instance_name(index)
    model = MODEL_BY_POLARITY[point.polarity]

    # Every DUT gets unique nodes and ideal independent bias sources.
    d = f"d{index}"
    g = f"g{index}"
    s = f"s{index}"
    b = f"b{index}"

    if point.polarity == "nmos":
        # Source is zero. VBS = VB - VS, so reverse body bias uses VB=-|VBS|.
        vd = point.vds_abs_v
        vg = point.vgs_abs_v
        vs = 0.0
        vb = -point.vbs_abs_v
    else:
        # PMOS source is zero. Negative terminal voltages produce:
        # |VSG|, |VSD| and |VSB| equal to the requested magnitudes.
        vd = -point.vds_abs_v
        vg = -point.vgs_abs_v
        vs = 0.0
        vb = point.vbs_abs_v

    return [
        f"Vd{index} {d} 0 DC {vd:.12g}",
        f"Vg{index} {g} 0 DC {vg:.12g}",
        f"Vs{index} {s} 0 DC {vs:.12g}",
        f"Vb{index} {b} 0 DC {vb:.12g}",
        (
            f"X{xname[1:]} {d} {g} {s} {b} {model} "
            f"L={point.length_um:.12g} W={point.width_um:.12g}"
        ),
    ]


def build_deck(job: BatchJob) -> str:
    lines = [
        "* OpenAMS SKY130 dense MOS characterization",
        f'.lib "{job.library}" {job.corner}',
        f".temp {job.temperature_c:.12g}",
        ".options savecurrents",
        "",
    ]

    for index, point in enumerate(job.points):
        lines.extend(build_device_lines(point, index))
        lines.append("")

    lines.extend([
        ".control",
        "set noaskquit",
        "set numdgt=17",
        "op",
    ])

    # Print each metric independently. Missing vectors produce an error for that
    # line but do not prevent other metrics from being captured.
    for index, point in enumerate(job.points):
        xname = safe_instance_name(index)
        model = MODEL_BY_POLARITY[point.polarity]
        prefix = internal_mos_path(xname, model)
        lines.append(f"echo OPENAMS_POINT_BEGIN {index}")
        for csv_name, candidates in VECTOR_CANDIDATES.items():
            for candidate_index, vector_name in enumerate(candidates):
                alias = f"openams_{csv_name}_{candidate_index}_{index}"
                lines.append(f"let {alias} = {prefix}[{vector_name}]")
                lines.append(f"print {alias}")

        # Robust drain-current fallback. At deep-cutoff/extreme-body-bias
        # operating points some ngspice/BSIM builds omit the internal [id]
        # vector even though the operating point itself converged. The current
        # through the ideal drain-bias source is always available. Rank 99
        # makes the parser prefer the native device [id] vector when present.
        id_fallback = f"openams_id_abs_a_99_{index}"
        lines.append(f"let {id_fallback} = -i(Vd{index})")
        lines.append(f"print {id_fallback}")

        lines.append(f"echo OPENAMS_POINT_END {index}")

    lines.extend([
        "quit",
        ".endc",
        ".end",
        "",
    ])
    return "\n".join(lines)


BEGIN_RE = re.compile(r"OPENAMS_POINT_BEGIN\s+(\d+)")
END_RE = re.compile(r"OPENAMS_POINT_END\s+(\d+)")
VALUE_RE = re.compile(
    r"openams_(?P<metric>[a-zA-Z0-9_]+)_(?P<candidate>\d+)_(?P<index>\d+)"
    r"\s*=\s*(?P<value>[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?)"
)


def parse_ngspice_output(text: str, point_count: int) -> list[dict[str, float]]:
    raw: list[dict[str, tuple[int, float]]] = [dict() for _ in range(point_count)]

    for match in VALUE_RE.finditer(text):
        index = int(match.group("index"))
        if not 0 <= index < point_count:
            continue
        metric = match.group("metric")
        candidate_rank = int(match.group("candidate"))
        value = float(match.group("value"))
        previous = raw[index].get(metric)
        if previous is None or candidate_rank < previous[0]:
            raw[index][metric] = (candidate_rank, value)

    return [
        {metric: value for metric, (_, value) in point_values.items()}
        for point_values in raw
    ]


def derived_values(row: dict[str, float | str | int]) -> dict[str, float | int]:
    def number(name: str) -> float:
        value = row.get(name, math.nan)
        try:
            return float(value)
        except (TypeError, ValueError):
            return math.nan

    width = number("width_um")
    current = abs(number("id_abs_a"))
    gm = abs(number("gm_s"))
    gds = abs(number("gds_s"))
    cgg = abs(number("cgg_f"))

    gm_over_id = gm / current if current > 0 and math.isfinite(gm) else math.nan
    ro = 1.0 / gds if gds > 0 else math.nan
    intrinsic_gain = gm / gds if gm >= 0 and gds > 0 else math.nan
    intrinsic_gain_db = (
        20.0 * math.log10(intrinsic_gain)
        if intrinsic_gain > 0
        else math.nan
    )
    ft_est = gm / (2.0 * math.pi * cgg) if gm >= 0 and cgg > 0 else math.nan

    return {
        "gm_over_id_1_v": gm_over_id,
        "ro_ohm": ro,
        "intrinsic_gain_v_v": intrinsic_gain,
        "intrinsic_gain_db": intrinsic_gain_db,
        "cgg_total_f": cgg,
        "ft_est_hz": ft_est,
        "id_per_width_a_per_um": current / width if width > 0 else math.nan,
        "gm_per_width_s_per_um": gm / width if width > 0 else math.nan,
        "gds_per_width_s_per_um": gds / width if width > 0 else math.nan,
    }


def run_batch(job: BatchJob) -> tuple[int, list[dict[str, object]], str]:
    deck = build_deck(job)

    if job.keep_decks_dir:
        deck_dir = Path(job.keep_decks_dir)
        deck_dir.mkdir(parents=True, exist_ok=True)
        deck_path = deck_dir / f"batch_{job.job_id:07d}.spice"
        log_path = deck_dir / f"batch_{job.job_id:07d}.log"
        deck_path.write_text(deck)
        temporary = False
    else:
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".spice", prefix="openams_mos_", delete=False
        )
        handle.write(deck)
        handle.close()
        deck_path = Path(handle.name)
        log_path = None
        temporary = True

    try:
        completed = subprocess.run(
            [job.ngspice, "-b", str(deck_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=job.timeout_s,
            check=False,
        )
        output = completed.stdout or ""

        if log_path:
            log_path.write_text(output)

        parsed = parse_ngspice_output(output, len(job.points))
        rows: list[dict[str, object]] = []

        for point, metrics in zip(job.points, parsed):
            model = MODEL_BY_POLARITY[point.polarity]
            row: dict[str, object] = {
                "polarity": point.polarity,
                "model": model,
                "corner": job.corner,
                "temperature_c": job.temperature_c,
                "length_um": point.length_um,
                "width_um": point.width_um,
                "vgs_abs_v": point.vgs_abs_v,
                "vds_abs_v": point.vds_abs_v,
                "vbs_abs_v": point.vbs_abs_v,
            }

            # Normalize signs. The dataset uses absolute magnitudes for both
            # NMOS and PMOS DC quantities, matching the legacy table.
            for metric in LEGACY_COLUMNS + ADDED_RAW_COLUMNS:
                if metric in row:
                    continue
                value = metrics.get(metric, math.nan)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    if metric in {
                        "id_abs_a", "vdsat_abs_v", "vth_abs_v",
                        "gm_s", "gds_s", "gmb_s",
                    }:
                        value = abs(value)
                row[metric] = value

            vdsat = float(row.get("vdsat_abs_v", math.nan))
            row["saturated"] = int(
                math.isfinite(vdsat)
                and point.vds_abs_v >= vdsat + job.sat_margin_v
            )

            missing_required = [
                name for name in REQUIRED_METRICS
                if not math.isfinite(float(row.get(name, math.nan)))
            ]
            missing_all = [
                name for name in VECTOR_CANDIDATES
                if not math.isfinite(float(row.get(name, math.nan)))
            ]

            row.update(derived_values(row))
            row["simulation_valid"] = int(
                completed.returncode == 0
                and (job.allow_missing_metrics or not missing_required)
            )
            row["missing_metric_count"] = len(missing_all)
            rows.append(row)

        return job.job_id, rows, output

    except subprocess.TimeoutExpired as exc:
        error = f"ngspice timeout after {job.timeout_s}s: {exc}"
        rows = []
        for point in job.points:
            row: dict[str, object] = {
                "polarity": point.polarity,
                "model": MODEL_BY_POLARITY[point.polarity],
                "corner": job.corner,
                "temperature_c": job.temperature_c,
                "length_um": point.length_um,
                "width_um": point.width_um,
                "vgs_abs_v": point.vgs_abs_v,
                "vds_abs_v": point.vds_abs_v,
                "vbs_abs_v": point.vbs_abs_v,
                "saturated": 0,
                "simulation_valid": 0,
                "missing_metric_count": len(VECTOR_CANDIDATES),
            }
            for name in OUTPUT_COLUMNS:
                row.setdefault(name, math.nan)
            rows.append(row)
        return job.job_id, rows, error
    finally:
        if temporary:
            deck_path.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ngspice_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
        return (result.stdout or "").strip()
    except Exception as exc:  # metadata collection must not abort a run
        return f"unavailable: {exc}"


def existing_keys(path: Path) -> set[tuple[str, float, float, float, float, float]]:
    if not path.exists():
        return set()
    keys = set()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(LEGACY_COLUMNS[:9]) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Cannot resume {path}: missing key columns {sorted(missing)}"
            )
        for row in reader:
            keys.add(row_key(row))
    return keys


def write_rows(
    writer: csv.DictWriter,
    rows: Sequence[dict[str, object]],
    allow_missing_metrics: bool,
) -> None:
    for row in rows:
        if not allow_missing_metrics and int(row["simulation_valid"]) != 1:
            missing = [
                name for name in REQUIRED_METRICS
                if not math.isfinite(float(row.get(name, math.nan)))
            ]
            raise RuntimeError(
                "Required ngspice metrics are unavailable for point "
                f"{row['polarity']} L={row['length_um']} W={row['width_um']} "
                f"VGS={row['vgs_abs_v']} VDS={row['vds_abs_v']} "
                f"VBS={row['vbs_abs_v']}. Missing: {missing}. "
                "Run --probe-only and inspect the retained deck/log, or use "
                "--allow-missing-metrics only for diagnostic runs."
            )
        writer.writerow({name: row.get(name, math.nan) for name in OUTPUT_COLUMNS})


def print_probe(rows: Sequence[dict[str, object]], output: str) -> None:
    print("\n===== PROBE RESULT =====")
    for row in rows:
        print(
            f"{row['polarity']} "
            f"L={row['length_um']}um W={row['width_um']}um "
            f"VGS={row['vgs_abs_v']}V VDS={row['vds_abs_v']}V "
            f"VBS={row['vbs_abs_v']}V"
        )
        for name in VECTOR_CANDIDATES:
            print(f"  {name:18s} = {row.get(name)}")
        print(f"  simulation_valid   = {row.get('simulation_valid')}")
        print(f"  missing_metrics    = {row.get('missing_metric_count')}")

    invalid = [r for r in rows if int(r["simulation_valid"]) != 1]
    if invalid:
        print("\n===== NGSPICE OUTPUT (probe failed) =====")
        print(output[-12000:])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate dense SKY130 MOS DC/small-signal MLP dataset"
    )
    parser.add_argument("--library", required=True, help="sky130.lib.spice path")
    parser.add_argument("--corner", default="tt")
    parser.add_argument("--temperature-c", type=float, default=27.0)
    parser.add_argument(
        "--profile",
        choices=("smoke", "dense", "technology"),
        default="smoke",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--sat-margin-v", type=float, default=0.05)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--allow-missing-metrics", action="store_true")
    parser.add_argument(
        "--keep-decks-dir",
        help="Keep generated ngspice decks and logs for debugging",
    )
    parser.add_argument(
        "--polarities",
        default="nmos,pmos",
        help="Comma-separated subset of nmos,pmos",
    )
    parser.add_argument("--lengths-um", help="Override profile grid")
    parser.add_argument("--widths-um", help="Override profile grid")
    parser.add_argument("--vgs-v", help="Override profile grid")
    parser.add_argument("--vds-v", help="Override profile grid")
    parser.add_argument("--vbs-v", help="Override profile grid")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    library = Path(args.library).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    metadata_path = output.with_suffix(output.suffix + ".metadata.json")

    if not library.is_file():
        raise SystemExit(f"SKY130 library not found: {library}")
    if shutil.which(args.ngspice) is None:
        raise SystemExit(f"ngspice executable not found: {args.ngspice}")
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")

    grids = profile_grids(args.profile)
    override_map = {
        "lengths_um": args.lengths_um,
        "widths_um": args.widths_um,
        "vgs_v": args.vgs_v,
        "vds_v": args.vds_v,
        "vbs_v": args.vbs_v,
    }
    for key, override in override_map.items():
        if override:
            grids[key] = parse_number_list(override)

    polarities = [p.strip().lower() for p in args.polarities.split(",") if p.strip()]
    unknown = set(polarities) - set(MODEL_BY_POLARITY)
    if unknown:
        raise SystemExit(f"Unknown polarities: {sorted(unknown)}")

    total_requested = (
        len(polarities)
        * len(grids["lengths_um"])
        * len(grids["widths_um"])
        * len(grids["vgs_v"])
        * len(grids["vds_v"])
        * len(grids["vbs_v"])
    )

    print("===== SKY130 CHARACTERIZATION CONFIGURATION =====")
    print(f"profile:         {args.profile}")
    print(f"library:         {library}")
    print(f"corner:          {args.corner}")
    print(f"temperature_c:   {args.temperature_c}")
    print(f"polarities:      {polarities}")
    print(f"length_count:    {len(grids['lengths_um'])}")
    print(f"width_count:     {len(grids['widths_um'])}")
    print(f"vgs_count:       {len(grids['vgs_v'])}")
    print(f"vds_count:       {len(grids['vds_v'])}")
    print(f"vbs_count:       {len(grids['vbs_v'])}")
    print(f"requested_rows:  {total_requested:,}")
    print(f"batch_size:      {args.batch_size}")
    print(f"workers:         {args.workers}")

    # Always probe both devices at representative bias before a production run.
    probe_points = tuple(
        BiasPoint(
            polarity=p,
            length_um=0.5,
            width_um=2.0,
            vgs_abs_v=0.8,
            vds_abs_v=0.8,
            vbs_abs_v=0.0,
        )
        for p in polarities
    )
    probe_job = BatchJob(
        job_id=-1,
        points=probe_points,
        library=str(library),
        corner=args.corner,
        temperature_c=args.temperature_c,
        ngspice=args.ngspice,
        sat_margin_v=args.sat_margin_v,
        timeout_s=args.timeout_s,
        keep_decks_dir=args.keep_decks_dir,
        allow_missing_metrics=args.allow_missing_metrics,
    )
    _, probe_rows, probe_output = run_batch(probe_job)
    print_probe(probe_rows, probe_output)

    probe_invalid = [r for r in probe_rows if int(r["simulation_valid"]) != 1]
    if probe_invalid and not args.allow_missing_metrics:
        raise SystemExit(
            "\n[FAIL] Probe did not expose all required DC/small-signal vectors. "
            "No dataset was generated. Re-run with --keep-decks-dir to inspect "
            "the exact ngspice deck and output."
        )
    if args.probe_only:
        print("\n[PASS] Probe completed; production sweep was not started.")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    completed = existing_keys(output) if args.resume else set()

    remaining = total_requested - len(completed)
    if remaining < 0:
        remaining = 0
    print(f"already_complete: {len(completed):,}")
    print(f"remaining_rows:   {remaining:,}")

    points = generate_points(
        polarities=polarities,
        lengths_um=grids["lengths_um"],
        widths_um=grids["widths_um"],
        vgs_v=grids["vgs_v"],
        vds_v=grids["vds_v"],
        vbs_v=grids["vbs_v"],
        completed=completed,
    )

    jobs = [
        BatchJob(
            job_id=job_id,
            points=batch,
            library=str(library),
            corner=args.corner,
            temperature_c=args.temperature_c,
            ngspice=args.ngspice,
            sat_margin_v=args.sat_margin_v,
            timeout_s=args.timeout_s,
            keep_decks_dir=args.keep_decks_dir,
            allow_missing_metrics=args.allow_missing_metrics,
        )
        for job_id, batch in enumerate(chunked(points, args.batch_size))
    ]

    mode = "a" if args.resume and output.exists() else "w"
    write_header = mode == "w" or output.stat().st_size == 0
    rows_written = 0
    start = time.monotonic()

    # Preserve deterministic CSV order despite parallel batch completion.
    pending_results: dict[int, list[dict[str, object]]] = {}
    next_job_to_write = 0

    with output.open(mode, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        if write_header:
            writer.writeheader()

        if args.workers == 1:
            for job in jobs:
                job_id, rows, _ = run_batch(job)
                write_rows(writer, rows, args.allow_missing_metrics)
                handle.flush()
                rows_written += len(rows)
                elapsed = max(time.monotonic() - start, 1e-9)
                print(
                    f"\r[INFO] rows={rows_written:,}/{remaining:,} "
                    f"rate={rows_written/elapsed:.1f} rows/s",
                    end="",
                    flush=True,
                )
        else:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                future_map = {pool.submit(run_batch, job): job.job_id for job in jobs}
                for future in as_completed(future_map):
                    job_id, rows, _ = future.result()
                    pending_results[job_id] = rows

                    while next_job_to_write in pending_results:
                        ready = pending_results.pop(next_job_to_write)
                        write_rows(writer, ready, args.allow_missing_metrics)
                        handle.flush()
                        rows_written += len(ready)
                        next_job_to_write += 1

                    elapsed = max(time.monotonic() - start, 1e-9)
                    print(
                        f"\r[INFO] rows={rows_written:,}/{remaining:,} "
                        f"rate={rows_written/elapsed:.1f} rows/s",
                        end="",
                        flush=True,
                    )

    print()
    elapsed = time.monotonic() - start

    metadata = {
        "schema_version": 1,
        "dataset_kind": "sky130_mos_dc_small_signal_characterization",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_csv": str(output),
        "output_columns": OUTPUT_COLUMNS,
        "legacy_compatible_columns": LEGACY_COLUMNS,
        "added_raw_columns": ADDED_RAW_COLUMNS,
        "derived_columns": DERIVED_COLUMNS,
        "pdk_library": str(library),
        "pdk_library_sha256": sha256_file(library),
        "corner": args.corner,
        "temperature_c": args.temperature_c,
        "models": MODEL_BY_POLARITY,
        "ngspice_executable": args.ngspice,
        "ngspice_version": ngspice_version(args.ngspice),
        "profile": args.profile,
        "grids": grids,
        "polarities": polarities,
        "requested_row_count": total_requested,
        "previously_completed_row_count": len(completed),
        "new_row_count": rows_written,
        "batch_size": args.batch_size,
        "workers": args.workers,
        "saturation_definition": (
            "vds_abs_v >= vdsat_abs_v + sat_margin_v"
        ),
        "sat_margin_v": args.sat_margin_v,
        "voltage_convention": {
            "nmos": "positive |VGS|, |VDS|; body at -|VBS| relative to source",
            "pmos": "negative VG and VD; positive body gives requested |VSB|",
            "csv": "absolute voltage and principal DC magnitude convention",
        },
        "vector_candidates": VECTOR_CANDIDATES,
        "required_metrics": sorted(REQUIRED_METRICS),
        "allow_missing_metrics": args.allow_missing_metrics,
        "elapsed_s": elapsed,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")

    print(f"[PASS] wrote {output}")
    print(f"[PASS] wrote {metadata_path}")
    print(f"[INFO] new_rows={rows_written:,}")
    print(f"[INFO] elapsed_s={elapsed:.2f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[FAIL] interrupted", file=sys.stderr)
        raise SystemExit(130)

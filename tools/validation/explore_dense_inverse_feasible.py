#!/usr/bin/env python3
"""Explore inverse-feasible tuple counts in a dense MOS technology dataset."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Iterable


@dataclass(frozen=True)
class Row:
    polarity: str
    model: str
    length_um: float
    width_um: float
    vgs_v: float
    vds_v: float
    vbs_v: float
    id_a: float
    vdsat_v: float | None
    saturated: bool
    simulation_valid: bool


def parse_float_list(text: str) -> list[float]:
    values: list[float] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        value = float(token)
        if not math.isfinite(value) or value <= 0:
            raise argparse.ArgumentTypeError(
                f"current must be finite and positive: {token!r}"
            )
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("at least one current is required")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure inverse-feasible branching in a dense MOS dataset."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("technology/sky130_tt_27c_mlp_dense.csv"),
    )
    parser.add_argument(
        "--polarity",
        choices=("nmos", "pmos", "both"),
        default="both",
    )
    parser.add_argument("--length-um", type=float, default=0.5)
    parser.add_argument(
        "--vbs-v",
        type=float,
        default=0.0,
        help="Absolute body-source voltage.",
    )
    parser.add_argument("--vbs-tolerance-v", type=float, default=1e-12)
    parser.add_argument(
        "--currents-ua",
        type=parse_float_list,
        default=parse_float_list("10,20,30,37.5,40,50"),
        help="Comma-separated target currents in microamps.",
    )
    parser.add_argument("--current-relative-tolerance", type=float, default=0.10)
    parser.add_argument("--current-absolute-tolerance-ua", type=float, default=1.0)
    parser.add_argument(
        "--require-saturated",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--require-simulation-valid",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime/inverse_feasible_dense_exploration"),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Limit printed tuple rows per current/polarity. Use 0 for all.",
    )
    return parser.parse_args()


def truth(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {
        "1", "true", "yes", "y", "saturated"
    }


def number(raw: dict[str, str], *names: str) -> float | None:
    for name in names:
        value = raw.get(name)
        if value in (None, ""):
            continue
        try:
            result = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(result):
            return result
    return None


def load_rows(path: Path) -> list[Row]:
    rows: list[Row] = []
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        for raw in reader:
            length_um = number(raw, "length_um", "l_um")
            width_um = number(raw, "width_um", "w_um")
            vgs_v = number(raw, "vgs_abs_v", "vgs_v")
            vds_v = number(raw, "vds_abs_v", "vds_v")
            vbs_v = number(raw, "vbs_abs_v", "vbs_v")
            id_a = number(raw, "id_abs_a", "id_a", "id")
            vdsat_v = number(raw, "vdsat_abs_v", "vdsat_v", "vdsat")
            required = (length_um, width_um, vgs_v, vds_v, vbs_v, id_a)
            if any(value is None for value in required):
                continue
            rows.append(
                Row(
                    polarity=str(raw.get("polarity", "")).strip().lower(),
                    model=str(raw.get("model", "")).strip(),
                    length_um=abs(float(length_um)),
                    width_um=abs(float(width_um)),
                    vgs_v=abs(float(vgs_v)),
                    vds_v=abs(float(vds_v)),
                    vbs_v=abs(float(vbs_v)),
                    id_a=abs(float(id_a)),
                    vdsat_v=abs(float(vdsat_v)) if vdsat_v is not None else None,
                    saturated=truth(raw.get("saturated", True)),
                    simulation_valid=truth(raw.get("simulation_valid", True)),
                )
            )
    if not rows:
        raise RuntimeError(f"no usable rows loaded from {path}")
    return rows


def q(value: float, digits: int = 12) -> float:
    return round(float(value), digits)


def selected_polarities(token: str) -> tuple[str, ...]:
    return ("nmos", "pmos") if token == "both" else (token,)


def analyze_current(
    rows: Iterable[Row],
    *,
    polarity: str,
    target_current_a: float,
    length_um: float,
    vbs_v: float,
    vbs_tolerance_v: float,
    relative_tolerance: float,
    absolute_tolerance_a: float,
    require_saturated: bool,
    require_simulation_valid: bool,
) -> dict[str, object]:
    allowed_error = max(absolute_tolerance_a, relative_tolerance * target_current_a)
    matched: list[Row] = []
    for row in rows:
        if row.polarity != polarity:
            continue
        if not math.isclose(row.length_um, length_um, rel_tol=0.0, abs_tol=1e-12):
            continue
        if abs(row.vbs_v - vbs_v) > vbs_tolerance_v:
            continue
        if require_saturated and not row.saturated:
            continue
        if require_simulation_valid and not row.simulation_valid:
            continue
        if abs(row.id_a - target_current_a) > allowed_error:
            continue
        matched.append(row)

    grouped: dict[tuple[float, float], list[Row]] = defaultdict(list)
    for row in matched:
        grouped[(q(row.width_um), q(row.vgs_v))].append(row)

    tuples: list[dict[str, object]] = []
    for (width_um, vgs_v), support in sorted(grouped.items()):
        best = min(support, key=lambda item: abs(item.id_a - target_current_a))
        vdsat_values = [row.vdsat_v for row in support if row.vdsat_v is not None]
        tuples.append(
            {
                "polarity": polarity,
                "target_current_ua": target_current_a * 1e6,
                "width_um": width_um,
                "vgs_v": vgs_v,
                "supporting_vds_count": len({q(row.vds_v) for row in support}),
                "vds_min_v": min(row.vds_v for row in support),
                "vds_max_v": max(row.vds_v for row in support),
                "vds_values_v": sorted({q(row.vds_v) for row in support}),
                "id_min_ua": min(row.id_a for row in support) * 1e6,
                "id_max_ua": max(row.id_a for row in support) * 1e6,
                "closest_id_ua": best.id_a * 1e6,
                "closest_id_error_ua": (best.id_a - target_current_a) * 1e6,
                "closest_id_error_percent": 100.0 * (best.id_a - target_current_a) / target_current_a,
                "vdsat_min_v": min(vdsat_values) if vdsat_values else None,
                "vdsat_max_v": max(vdsat_values) if vdsat_values else None,
                "closest_vds_v": best.vds_v,
                "closest_vdsat_v": best.vdsat_v,
            }
        )

    return {
        "polarity": polarity,
        "target_current_ua": target_current_a * 1e6,
        "allowed_current_error_ua": allowed_error * 1e6,
        "raw_matching_row_count": len(matched),
        "unique_width_count": len({item["width_um"] for item in tuples}),
        "unique_vgs_count": len({item["vgs_v"] for item in tuples}),
        "unique_w_vgs_tuple_count": len(tuples),
        "unique_w_vgs_vds_tuple_count": len({(q(row.width_um), q(row.vgs_v), q(row.vds_v)) for row in matched}),
        "average_vds_rows_per_w_vgs_tuple": mean(item["supporting_vds_count"] for item in tuples) if tuples else 0.0,
        "median_vds_rows_per_w_vgs_tuple": median(item["supporting_vds_count"] for item in tuples) if tuples else 0.0,
        "tuples": tuples,
    }


def write_tuple_csv(path: Path, analyses: list[dict[str, object]]) -> None:
    rows: list[dict[str, object]] = []
    for analysis in analyses:
        rows.extend(analysis["tuples"])  # type: ignore[arg-type]
    fields = [
        "polarity", "target_current_ua", "width_um", "vgs_v",
        "supporting_vds_count", "vds_min_v", "vds_max_v", "vds_values_v",
        "id_min_ua", "id_max_ua", "closest_id_ua", "closest_id_error_ua",
        "closest_id_error_percent", "vdsat_min_v", "vdsat_max_v",
        "closest_vds_v", "closest_vdsat_v",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            output = dict(row)
            output["vds_values_v"] = json.dumps(output["vds_values_v"], separators=(",", ":"))
            writer.writerow(output)


def main() -> int:
    args = parse_args()
    dataset = args.dataset.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(dataset)

    analyses: list[dict[str, object]] = []
    for polarity in selected_polarities(args.polarity):
        for current_ua in args.currents_ua:
            analyses.append(
                analyze_current(
                    rows,
                    polarity=polarity,
                    target_current_a=current_ua * 1e-6,
                    length_um=args.length_um,
                    vbs_v=args.vbs_v,
                    vbs_tolerance_v=args.vbs_tolerance_v,
                    relative_tolerance=args.current_relative_tolerance,
                    absolute_tolerance_a=args.current_absolute_tolerance_ua * 1e-6,
                    require_saturated=args.require_saturated,
                    require_simulation_valid=args.require_simulation_valid,
                )
            )

    summary = {
        "artifact": "openams.inverse_feasible_dense_exploration",
        "schema_version": 1,
        "dataset": str(dataset),
        "loaded_row_count": len(rows),
        "length_um": args.length_um,
        "vbs_v": args.vbs_v,
        "vbs_tolerance_v": args.vbs_tolerance_v,
        "current_relative_tolerance": args.current_relative_tolerance,
        "current_absolute_tolerance_ua": args.current_absolute_tolerance_ua,
        "require_saturated": args.require_saturated,
        "require_simulation_valid": args.require_simulation_valid,
        "analyses": [{key: value for key, value in analysis.items() if key != "tuples"} for analysis in analyses],
    }

    summary_path = output_dir / "summary.json"
    tuples_path = output_dir / "inverse_feasible_tuples.csv"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_tuple_csv(tuples_path, analyses)

    print("===== DENSE INVERSE-FEASIBLE EXPLORATION =====")
    print("dataset:", dataset)
    print("loaded rows:", len(rows))
    print()
    for analysis in analyses:
        print(f"{analysis['polarity']} Id={analysis['target_current_ua']:.6g} uA")
        print("  raw rows:", analysis["raw_matching_row_count"])
        print("  unique (W,VGS):", analysis["unique_w_vgs_tuple_count"])
        print("  unique (W,VGS,VDS):", analysis["unique_w_vgs_vds_tuple_count"])
        print("  unique widths:", analysis["unique_width_count"])
        print("  unique VGS:", analysis["unique_vgs_count"])
        print("  average VDS rows per tuple:", f"{analysis['average_vds_rows_per_w_vgs_tuple']:.3f}")
        tuples = analysis["tuples"]
        limit = len(tuples) if args.top <= 0 else min(args.top, len(tuples))
        for item in tuples[:limit]:
            print(
                "   ",
                f"W={item['width_um']:.6g} um",
                f"VGS={item['vgs_v']:.6g} V",
                f"VDS=[{item['vds_min_v']:.6g},{item['vds_max_v']:.6g}] V",
                f"VDSAT=[{item['vdsat_min_v']},{item['vdsat_max_v']}] V",
                f"closest_Id={item['closest_id_ua']:.6g} uA",
            )
        if limit < len(tuples):
            print(f"    ... {len(tuples) - limit} more tuples")
        print()
    print("summary:", summary_path)
    print("tuples:", tuples_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

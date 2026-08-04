#!/usr/bin/env python3
"""Analyze extrema, distributions, and correlations in an OpenAMS benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


COLUMN_ALIASES = {
    "gain_db": ("gain_est_db", "gain_db"),
    "ugb_hz": ("ugb_est_hz", "ugb_hz"),
    "phase_margin_deg": ("phase_margin_est_deg", "phase_margin_deg"),
    "power_w": ("power_est_w", "pdiss_est_w", "pdiss_w", "power_w"),
    "w_m1_um": ("w_m1_um", "m1_width_um", "w1_um"),
    "w_m3_um": ("w_m3_um", "m3_width_um", "w3_um"),
    "w_m6_um": ("w_m6_um", "m6_width_um", "w6_um"),
    "i_m5_a": ("i_m5_a", "m5_current_a", "i5_a"),
    "vout_v": ("vout_v", "vout_target_v", "vout_constructed_v"),
}

METRICS = tuple(COLUMN_ALIASES)
PERCENTILES = (0, 5, 25, 50, 75, 95, 100)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--status-column", default="status")
    p.add_argument("--pass-value", default="PASS")
    p.add_argument("--top-count", type=int, default=10)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in fieldnames:
                resolved[canonical] = alias
                break
    return resolved


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if args.top_count <= 0:
        raise ValueError("--top-count must be positive")

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "extrema": output_dir / "extrema_full_rows.csv",
        "distribution": output_dir / "distribution_summary.csv",
        "correlation": output_dir / "correlation_matrix.csv",
        "summary": output_dir / "extrema_summary.json",
        "report": output_dir / "BENCHMARK_EXTREMA_REPORT.md",
    }

    if not args.overwrite:
        existing = [str(path) for path in outputs.values() if path.exists()]
        if existing:
            raise FileExistsError("Outputs already exist: " + ", ".join(existing))

    with input_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    if not fieldnames:
        raise ValueError(f"No CSV header found in {input_path}")
    if args.status_column not in fieldnames:
        raise KeyError(f"Missing status column: {args.status_column}")

    accepted = [
        row for row in rows
        if row.get(args.status_column) == args.pass_value
    ]
    if not accepted:
        raise ValueError("No accepted rows found")

    resolved = resolve_columns(fieldnames)
    missing = [metric for metric in METRICS if metric not in resolved]

    extrema_rows: list[dict[str, Any]] = []
    distribution_rows: list[dict[str, Any]] = []
    extrema_summary: dict[str, Any] = {}

    for metric in METRICS:
        if metric not in resolved:
            continue

        column = resolved[metric]
        values = [
            (number, row)
            for row in accepted
            if (number := finite_float(row.get(column))) is not None
        ]
        if not values:
            continue

        values.sort(
            key=lambda item: (
                item[0],
                int(item[1].get("grid_index", "0") or 0),
            )
        )

        lows = values[: args.top_count]
        highs = list(reversed(values[-args.top_count:]))

        extrema_summary[metric] = {
            "source_column": column,
            "minimum": lows[0][0],
            "maximum": highs[0][0],
            "lowest_grid_indices": [row.get("grid_index") for _, row in lows],
            "highest_grid_indices": [row.get("grid_index") for _, row in highs],
        }

        for direction, selected in (("LOWEST", lows), ("HIGHEST", highs)):
            for rank, (value, row) in enumerate(selected, 1):
                extrema_rows.append(
                    {
                        "extremum_metric": metric,
                        "extremum_direction": direction,
                        "extremum_rank": rank,
                        "extremum_value": value,
                        "source_column": column,
                        **row,
                    }
                )

        array = np.asarray([value for value, _ in values], dtype=float)
        p = np.percentile(array, PERCENTILES)
        distribution_rows.append(
            {
                "metric": metric,
                "source_column": column,
                "count": len(array),
                "minimum": p[0],
                "p05": p[1],
                "p25": p[2],
                "median": p[3],
                "p75": p[4],
                "p95": p[5],
                "maximum": p[6],
                "mean": float(np.mean(array)),
                "stddev": float(np.std(array)),
            }
        )

    write_csv(
        outputs["extrema"],
        [
            "extremum_metric",
            "extremum_direction",
            "extremum_rank",
            "extremum_value",
            "source_column",
            *fieldnames,
        ],
        extrema_rows,
    )

    write_csv(
        outputs["distribution"],
        [
            "metric",
            "source_column",
            "count",
            "minimum",
            "p05",
            "p25",
            "median",
            "p75",
            "p95",
            "maximum",
            "mean",
            "stddev",
        ],
        distribution_rows,
    )

    corr_metrics = [metric for metric in METRICS if metric in resolved]
    corr_rows: list[dict[str, Any]] = []

    for row_metric in corr_metrics:
        record: dict[str, Any] = {"metric": row_metric}

        for col_metric in corr_metrics:
            pairs = []
            for row in accepted:
                x = finite_float(row.get(resolved[row_metric]))
                y = finite_float(row.get(resolved[col_metric]))
                if x is not None and y is not None:
                    pairs.append((x, y))

            if len(pairs) < 2:
                record[col_metric] = ""
                continue

            x_values = np.asarray([x for x, _ in pairs], dtype=float)
            y_values = np.asarray([y for _, y in pairs], dtype=float)

            if np.std(x_values) == 0.0 or np.std(y_values) == 0.0:
                record[col_metric] = ""
            else:
                record[col_metric] = float(np.corrcoef(x_values, y_values)[0, 1])

        corr_rows.append(record)

    write_csv(
        outputs["correlation"],
        ["metric", *corr_metrics],
        corr_rows,
    )

    summary = {
        "status": "PASS",
        "input_csv": str(input_path),
        "total_rows": len(rows),
        "accepted_rows": len(accepted),
        "top_count": args.top_count,
        "resolved_columns": resolved,
        "missing_metrics": missing,
        "extrema": extrema_summary,
        "notes": {
            "phase_margin": (
                "These are OpenAMS-estimated phase margins. Current ngspice "
                "validation has shown a systematic phase-model disagreement."
            ),
            "w_m3": (
                "W3 is relevant to active-load and input common-mode behavior; "
                "CMRR also depends on tail-source output resistance, symmetry, "
                "and mismatch."
            ),
        },
        "outputs": {name: str(path) for name, path in outputs.items()},
    }
    outputs["summary"].write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    report_lines = [
        "# OpenAMS Benchmark Extrema Analysis",
        "",
        f"- Total rows: **{len(rows)}**",
        f"- Accepted rows: **{len(accepted)}**",
        f"- Top/bottom rows retained per metric: **{args.top_count}**",
        "",
        "## Resolved columns",
        "",
    ]

    for metric in METRICS:
        resolved_text = (
            f"`{resolved[metric]}`" if metric in resolved else "**MISSING**"
        )
        report_lines.append(f"- `{metric}` → {resolved_text}")

    report_lines += [
        "",
        "## Absolute extrema",
        "",
        "| Metric | Minimum | Maximum |",
        "|---|---:|---:|",
    ]

    for metric in METRICS:
        if metric in extrema_summary:
            item = extrema_summary[metric]
            report_lines.append(
                f"| {metric} | {item['minimum']:.10g} | {item['maximum']:.10g} |"
            )

    report_lines += [
        "",
        "## Important note",
        "",
        "Phase-margin extrema are model extrema only. The present ngspice "
        "validation has identified a systematic phase-model disagreement.",
        "",
        "## Generated files",
        "",
        "- `extrema_full_rows.csv`",
        "- `distribution_summary.csv`",
        "- `correlation_matrix.csv`",
        "- `extrema_summary.json`",
    ]

    outputs["report"].write_text("\n".join(report_lines) + "\n")

    print("===== OPENAMS BENCHMARK EXTREMA ANALYSIS =====")
    print(f"total rows:    {len(rows)}")
    print(f"accepted rows: {len(accepted)}")
    print(f"resolved:      {len(resolved)}/{len(METRICS)}")
    if missing:
        print("missing:")
        for metric in missing:
            print(f"  - {metric}")
    for name, path in outputs.items():
        print(f"{name}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

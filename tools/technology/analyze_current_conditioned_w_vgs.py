#!/usr/bin/env python3
"""Analyze saturated (W, VGS) tuple counts for target drain currents.

For every target current, this script finds unique (width_um, vgs_v) pairs
having at least one characterized VDS row that:

1. matches the target current within the configured tolerance; and
2. is classified as saturated.

This gives an estimate of the branching factor an inverse feasible-region
table would expose to circuit-level assignment synthesis.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


CURRENT_FIELDS = (
    "id_abs_a",
    "id_a",
    "id",
)

SATURATION_FIELDS = (
    "saturated",
    "is_saturated",
)

VDSAT_FIELDS = (
    "vdsat_abs_v",
    "vdsat_v",
    "vdsat",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--technology-csv",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output-csv",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--polarities",
        default="nmos,pmos",
        help="Comma-separated polarity list.",
    )

    parser.add_argument(
        "--length-um",
        type=float,
        default=0.5,
    )

    parser.add_argument(
        "--vbs-v",
        type=float,
        default=0.0,
    )

    parser.add_argument(
        "--vbs-tolerance-v",
        type=float,
        default=1e-12,
    )

    parser.add_argument(
        "--current-min-a",
        type=float,
        default=10e-6,
    )

    parser.add_argument(
        "--current-max-a",
        type=float,
        default=100e-6,
    )

    parser.add_argument(
        "--current-count",
        type=int,
        default=19,
        help="Number of uniformly spaced target currents.",
    )

    parser.add_argument(
        "--current-relative-tolerance",
        type=float,
        default=0.10,
    )

    parser.add_argument(
        "--current-absolute-tolerance-a",
        type=float,
        default=1e-6,
    )

    parser.add_argument(
        "--saturation-margin-v",
        type=float,
        default=0.0,
        help=(
            "Optional additional requirement: "
            "VDS >= VDSAT + margin."
        ),
    )

    parser.add_argument(
        "--max-example-tuples",
        type=int,
        default=10,
    )

    return parser.parse_args()


def number(
    row: dict[str, str],
    *names: str,
) -> float | None:
    for name in names:
        raw = row.get(name)

        if raw in (None, ""):
            continue

        try:
            return float(raw)
        except ValueError:
            continue

    return None


def boolean(
    row: dict[str, str],
    *names: str,
) -> bool | None:
    for name in names:
        raw = row.get(name)

        if raw in (None, ""):
            continue

        token = str(raw).strip().lower()

        if token in {
            "1",
            "true",
            "yes",
            "y",
            "saturation",
            "saturated",
        }:
            return True

        if token in {
            "0",
            "false",
            "no",
            "n",
            "linear",
            "triode",
        }:
            return False

    return None


def target_currents(
    minimum: float,
    maximum: float,
    count: int,
) -> list[float]:
    if count < 1:
        raise ValueError("current-count must be at least 1")

    if count == 1:
        return [minimum]

    step = (maximum - minimum) / (count - 1)

    return [
        minimum + index * step
        for index in range(count)
    ]


def percentile(
    values: list[float],
    fraction: float,
) -> float | None:
    if not values:
        return None

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return ordered[lower]

    weight = position - lower

    return (
        ordered[lower] * (1.0 - weight)
        + ordered[upper] * weight
    )


def is_saturated(
    row: dict[str, str],
    extra_margin_v: float,
) -> bool:
    explicit = boolean(
        row,
        *SATURATION_FIELDS,
    )

    if explicit is False:
        return False

    vds = number(
        row,
        "vds_v",
        "vds_abs_v",
    )

    vdsat = number(
        row,
        *VDSAT_FIELDS,
    )

    if vds is not None and vdsat is not None:
        return vds >= vdsat + extra_margin_v

    return explicit is True


def main() -> int:
    args = parse_args()

    polarities = {
        item.strip().lower()
        for item in args.polarities.split(",")
        if item.strip()
    }

    targets = target_currents(
        args.current_min_a,
        args.current_max_a,
        args.current_count,
    )

    records: list[dict[str, Any]] = []

    with args.technology_csv.open(
        newline="",
        encoding="utf-8",
    ) as stream:
        reader = csv.DictReader(stream)

        for index, row in enumerate(reader):
            polarity = str(
                row.get("polarity", "")
            ).strip().lower()

            if polarity not in polarities:
                continue

            length_um = number(
                row,
                "length_um",
                "l_um",
            )

            if (
                length_um is None
                or not math.isclose(
                    length_um,
                    args.length_um,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                continue

            vbs_v = number(
                row,
                "vbs_v",
                "vbs_abs_v",
            )

            if (
                vbs_v is None
                or not math.isclose(
                    vbs_v,
                    args.vbs_v,
                    rel_tol=0.0,
                    abs_tol=args.vbs_tolerance_v,
                )
            ):
                continue

            current_a = number(
                row,
                *CURRENT_FIELDS,
            )

            width_um = number(
                row,
                "width_um",
                "w_um",
            )

            vgs_v = number(
                row,
                "vgs_v",
                "vgs_abs_v",
            )

            vds_v = number(
                row,
                "vds_v",
                "vds_abs_v",
            )

            vdsat_v = number(
                row,
                *VDSAT_FIELDS,
            )

            if (
                current_a is None
                or width_um is None
                or vgs_v is None
            ):
                continue

            if not is_saturated(
                row,
                args.saturation_margin_v,
            ):
                continue

            records.append(
                {
                    "row_index": index,
                    "polarity": polarity,
                    "current_a": abs(current_a),
                    "width_um": width_um,
                    "vgs_v": abs(vgs_v),
                    "vds_v": (
                        abs(vds_v)
                        if vds_v is not None
                        else None
                    ),
                    "vdsat_v": (
                        abs(vdsat_v)
                        if vdsat_v is not None
                        else None
                    ),
                }
            )

    if not records:
        raise SystemExit(
            "[FAIL] no matching saturated technology rows"
        )

    results: list[dict[str, Any]] = []

    for polarity in sorted(polarities):
        polarity_rows = [
            row
            for row in records
            if row["polarity"] == polarity
        ]

        for target_a in targets:
            allowed_error = max(
                args.current_absolute_tolerance_a,
                args.current_relative_tolerance
                * abs(target_a),
            )

            matches = [
                row
                for row in polarity_rows
                if abs(row["current_a"] - target_a)
                <= allowed_error
            ]

            grouped: dict[
                tuple[float, float],
                list[dict[str, Any]],
            ] = defaultdict(list)

            for row in matches:
                key = (
                    row["width_um"],
                    row["vgs_v"],
                )
                grouped[key].append(row)

            tuples: list[dict[str, Any]] = []

            for (width_um, vgs_v), rows in sorted(
                grouped.items()
            ):
                vds_values = [
                    row["vds_v"]
                    for row in rows
                    if row["vds_v"] is not None
                ]

                current_values = [
                    row["current_a"]
                    for row in rows
                ]

                best_row = min(
                    rows,
                    key=lambda row: abs(
                        row["current_a"] - target_a
                    ),
                )

                tuples.append(
                    {
                        "width_um": width_um,
                        "vgs_v": vgs_v,
                        "supporting_vds_count": len(
                            set(vds_values)
                        ),
                        "minimum_saturated_vds_v": (
                            min(vds_values)
                            if vds_values
                            else None
                        ),
                        "maximum_saturated_vds_v": (
                            max(vds_values)
                            if vds_values
                            else None
                        ),
                        "best_predicted_current_a": (
                            best_row["current_a"]
                        ),
                        "best_current_relative_error": (
                            abs(
                                best_row["current_a"]
                                - target_a
                            )
                            / max(abs(target_a), 1e-30)
                        ),
                        "matched_current_min_a": min(
                            current_values
                        ),
                        "matched_current_max_a": max(
                            current_values
                        ),
                    }
                )

            widths = sorted({
                item["width_um"]
                for item in tuples
            })

            vgs_values = sorted({
                item["vgs_v"]
                for item in tuples
            })

            results.append(
                {
                    "polarity": polarity,
                    "target_current_a": target_a,
                    "target_current_ua": target_a * 1e6,
                    "allowed_current_error_a": (
                        allowed_error
                    ),
                    "matching_saturated_row_count": len(
                        matches
                    ),
                    "unique_w_vgs_tuple_count": len(
                        tuples
                    ),
                    "unique_width_count": len(widths),
                    "unique_vgs_count": len(vgs_values),
                    "minimum_width_um": (
                        min(widths)
                        if widths
                        else None
                    ),
                    "maximum_width_um": (
                        max(widths)
                        if widths
                        else None
                    ),
                    "minimum_vgs_v": (
                        min(vgs_values)
                        if vgs_values
                        else None
                    ),
                    "maximum_vgs_v": (
                        max(vgs_values)
                        if vgs_values
                        else None
                    ),
                    "example_tuples": tuples[
                        : args.max_example_tuples
                    ],
                }
            )

    summary_by_polarity: dict[str, Any] = {}

    for polarity in sorted(polarities):
        counts = [
            float(item["unique_w_vgs_tuple_count"])
            for item in results
            if (
                item["polarity"] == polarity
                and item["unique_w_vgs_tuple_count"] > 0
            )
        ]

        all_counts = [
            float(item["unique_w_vgs_tuple_count"])
            for item in results
            if item["polarity"] == polarity
        ]

        summary_by_polarity[polarity] = {
            "target_current_count": len(all_counts),
            "target_currents_with_support": len(counts),
            "target_currents_without_support": (
                len(all_counts) - len(counts)
            ),
            "average_w_vgs_tuples_supported_currents": (
                statistics.mean(counts)
                if counts
                else 0.0
            ),
            "median_w_vgs_tuples_supported_currents": (
                statistics.median(counts)
                if counts
                else 0.0
            ),
            "minimum_w_vgs_tuples_supported_currents": (
                min(counts)
                if counts
                else 0.0
            ),
            "maximum_w_vgs_tuples_supported_currents": (
                max(counts)
                if counts
                else 0.0
            ),
            "p25_w_vgs_tuple_count": percentile(
                counts,
                0.25,
            ),
            "p75_w_vgs_tuple_count": percentile(
                counts,
                0.75,
            ),
            "p90_w_vgs_tuple_count": percentile(
                counts,
                0.90,
            ),
            "average_including_zero_support": (
                statistics.mean(all_counts)
                if all_counts
                else 0.0
            ),
        }

    payload = {
        "artifact": (
            "openams.current_conditioned_w_vgs_analysis"
        ),
        "schema_version": 1,
        "status": "PASS",
        "technology_csv": str(
            args.technology_csv.resolve()
        ),
        "filters": {
            "polarities": sorted(polarities),
            "length_um": args.length_um,
            "vbs_v": args.vbs_v,
            "current_min_a": args.current_min_a,
            "current_max_a": args.current_max_a,
            "current_count": args.current_count,
            "current_relative_tolerance": (
                args.current_relative_tolerance
            ),
            "current_absolute_tolerance_a": (
                args.current_absolute_tolerance_a
            ),
            "saturation_margin_v": (
                args.saturation_margin_v
            ),
        },
        "filtered_saturated_row_count": len(records),
        "summary_by_polarity": summary_by_polarity,
        "results": results,
    }

    args.output_json.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output_csv.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output_json.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    csv_fields = [
        "polarity",
        "target_current_a",
        "target_current_ua",
        "allowed_current_error_a",
        "matching_saturated_row_count",
        "unique_w_vgs_tuple_count",
        "unique_width_count",
        "unique_vgs_count",
        "minimum_width_um",
        "maximum_width_um",
        "minimum_vgs_v",
        "maximum_vgs_v",
    ]

    with args.output_csv.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=csv_fields,
        )
        writer.writeheader()

        for item in results:
            writer.writerow({
                key: item.get(key)
                for key in csv_fields
            })

    print(
        "===== CURRENT-CONDITIONED (W, VGS) ANALYSIS ====="
    )
    print(
        f"technology rows retained: {len(records)}"
    )

    for polarity, summary in summary_by_polarity.items():
        print()
        print(f"{polarity.upper()}:")
        print(
            "  target currents with support: "
            f"{summary['target_currents_with_support']}/"
            f"{summary['target_current_count']}"
        )
        print(
            "  average tuples/current: "
            f"{summary['average_w_vgs_tuples_supported_currents']:.3f}"
        )
        print(
            "  median tuples/current:  "
            f"{summary['median_w_vgs_tuples_supported_currents']:.3f}"
        )
        print(
            "  min/max tuples/current: "
            f"{summary['minimum_w_vgs_tuples_supported_currents']:.0f}/"
            f"{summary['maximum_w_vgs_tuples_supported_currents']:.0f}"
        )
        print(
            "  p25/p75/p90:            "
            f"{summary['p25_w_vgs_tuple_count']}, "
            f"{summary['p75_w_vgs_tuple_count']}, "
            f"{summary['p90_w_vgs_tuple_count']}"
        )

    print()
    print(f"JSON: {args.output_json}")
    print(f"CSV:  {args.output_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

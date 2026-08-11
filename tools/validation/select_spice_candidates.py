#!/usr/bin/env python3
"""
select_spice_candidates.py

Select a representative subset of circuit design-space points for SPICE
simulation, with emphasis on covering important transistor-width dimensions.

Default presets:
  two_stage:
      important dimensions = W1, W3, W6
  folded_cascode:
      important dimensions = W1, W4, W6

Selection method:
  1. Keep only eligible rows (PASS rows if a recognizable status column exists).
  2. Resolve important columns using common OpenAMS naming variants.
  3. Normalize each important dimension to [0, 1].
  4. Seed the selection with geometric extremes + center-nearest point.
  5. Fill the remaining budget by greedy farthest-point sampling:
         choose the point whose minimum distance to already-selected points
         is largest.
     This spreads points through the important-variable space instead of
     simply taking random samples or uniformly sampling CSV row number.
  6. Write the complete original rows plus selection metadata.

This is intended for selecting ngspice verification/training candidates that
will later be used to build an MLP surrogate for the topology.

Examples
--------
Two-stage opamp:
    python tools/validation/select_spice_candidates.py \
      --input two_stage_coverage_plan.csv \
      --topology two_stage \
      --count 100 \
      --output two_stage_spice_candidates_100.csv

Folded cascode:
    python tools/validation/select_spice_candidates.py \
      --input folded_cascode_design_space.csv \
      --topology folded_cascode \
      --count 100 \
      --output folded_cascode_spice_candidates_100.csv

Override dimensions explicitly:
    python tools/validation/select_spice_candidates.py \
      --input my_space.csv \
      --columns w_m1_um w_m3_um w_m6_um \
      --count 200 \
      --output candidates.csv
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


PRESETS = {
    "two_stage": ["W1", "W3", "W6"],
    "two-stage": ["W1", "W3", "W6"],
    "two_stage_opamp": ["W1", "W3", "W6"],
    "folded_cascode": ["W1", "W4", "W6"],
    "folded-cascode": ["W1", "W4", "W6"],
    "folded": ["W1", "W4", "W6"],
}


def normalized_name(name: str) -> str:
    return "".join(ch.lower() for ch in str(name) if ch.isalnum())


def aliases_for_device_width(device: str) -> list[str]:
    d = device.lower().replace("m", "")
    return [
        f"w_m{d}_um",
        f"wm{d}um",
        f"w{d}_um",
        f"w{d}um",
        f"w_m{d}",
        f"wm{d}",
        f"w{d}",
        f"m{d}_width_um",
        f"m{d}widthum",
        f"width_m{d}_um",
        f"widthm{d}um",
    ]


def resolve_column(df: pd.DataFrame, requested: str) -> str:
    """Resolve W1/W3/W6 or an explicit CSV column name."""
    cols = list(df.columns)

    # Exact match first.
    if requested in cols:
        return requested

    norm_to_original = {normalized_name(c): c for c in cols}
    req_norm = normalized_name(requested)

    if req_norm in norm_to_original:
        return norm_to_original[req_norm]

    # Device shorthand such as W1 -> common OpenAMS aliases.
    r = requested.strip().upper()
    if r.startswith("W") and r[1:].isdigit():
        device = f"M{r[1:]}"
        for alias in aliases_for_device_width(device):
            n = normalized_name(alias)
            if n in norm_to_original:
                return norm_to_original[n]

        # Last-resort structural match: column contains width/W + device index.
        idx = r[1:]
        candidates = []
        for c in cols:
            n = normalized_name(c)
            if (
                n in {f"w{idx}", f"wm{idx}", f"w{idx}um", f"wm{idx}um"}
                or n.startswith(f"wm{idx}")
                or n.startswith(f"w{idx}")
                or n.startswith(f"m{idx}width")
                or n.startswith(f"widthm{idx}")
            ):
                candidates.append(c)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise ValueError(
                f"Ambiguous mapping for {requested}: {candidates}. "
                f"Use --columns with exact CSV column names."
            )

    raise ValueError(
        f"Could not find a CSV column corresponding to '{requested}'.\n"
        f"Available columns:\n  " + "\n  ".join(map(str, cols))
    )


def find_status_column(df: pd.DataFrame) -> str | None:
    preferred = [
        "status",
        "result",
        "classification",
        "feasibility_status",
        "design_status",
        "pass_fail",
    ]
    norm_map = {normalized_name(c): c for c in df.columns}
    for p in preferred:
        n = normalized_name(p)
        if n in norm_map:
            return norm_map[n]
    return None


def eligible_rows(df: pd.DataFrame, status_column: str | None, include_all: bool):
    if include_all:
        return df.copy(), None

    status_column = status_column or find_status_column(df)
    if status_column is None:
        return df.copy(), None

    s = df[status_column].astype(str).str.strip().str.upper()

    # Only auto-filter if recognizable PASS-like values actually exist.
    pass_values = {"PASS", "PASSED", "VALID", "FEASIBLE", "TRUE", "1", "OK"}
    mask = s.isin(pass_values)
    if mask.any():
        return df.loc[mask].copy(), status_column

    return df.copy(), None


def finite_numeric_frame(df: pd.DataFrame, columns: list[str]):
    x = df[columns].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(x.to_numpy(dtype=float)).all(axis=1)
    return df.loc[finite].copy(), x.loc[finite].copy(), finite


def normalize_unit_cube(x: np.ndarray):
    lo = np.nanmin(x, axis=0)
    hi = np.nanmax(x, axis=0)
    span = hi - lo
    span[span == 0.0] = 1.0
    z = (x - lo) / span
    return z, lo, hi


def seed_indices(z: np.ndarray) -> list[int]:
    """
    Seed with:
      - min/max point of each dimension
      - nearest point to center
      - nearest points to all hypercube corners, if not too many dimensions

    Duplicates are removed while preserving order.
    """
    n, d = z.shape
    seeds: list[int] = []

    for j in range(d):
        seeds.append(int(np.argmin(z[:, j])))
        seeds.append(int(np.argmax(z[:, j])))

    center = np.full(d, 0.5)
    seeds.append(int(np.argmin(np.sum((z - center) ** 2, axis=1))))

    # For 3 dimensions this adds up to 8 meaningful boundary/corner seeds.
    # Cap at d <= 6 to avoid exponential growth.
    if d <= 6:
        for corner_id in range(1 << d):
            corner = np.array(
                [(corner_id >> j) & 1 for j in range(d)], dtype=float
            )
            idx = int(np.argmin(np.sum((z - corner) ** 2, axis=1)))
            seeds.append(idx)

    seen = set()
    unique = []
    for idx in seeds:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)
    return unique


def farthest_point_sample(z: np.ndarray, count: int) -> tuple[list[int], list[float]]:
    n = len(z)
    if count >= n:
        return list(range(n)), [math.nan] * n
    if count <= 0:
        return [], []

    selected = seed_indices(z)[:count]
    selected_set = set(selected)

    # distance-to-nearest-selected, squared Euclidean distance
    nearest_d2 = np.full(n, np.inf, dtype=float)
    for idx in selected:
        d2 = np.sum((z - z[idx]) ** 2, axis=1)
        nearest_d2 = np.minimum(nearest_d2, d2)

    nearest_d2[list(selected_set)] = -np.inf

    # Record the spacing score at the time each point is selected.
    score_map = {idx: math.nan for idx in selected}

    while len(selected) < count:
        idx = int(np.argmax(nearest_d2))
        score_map[idx] = float(math.sqrt(max(0.0, nearest_d2[idx])))
        selected.append(idx)
        selected_set.add(idx)

        d2 = np.sum((z - z[idx]) ** 2, axis=1)
        nearest_d2 = np.minimum(nearest_d2, d2)
        nearest_d2[idx] = -np.inf

    scores = [score_map[i] for i in selected]
    return selected, scores


def coverage_summary(z: np.ndarray, selected: list[int]) -> dict[str, float]:
    if not selected:
        return {}

    nearest = np.full(len(z), np.inf)
    for idx in selected:
        d = np.sqrt(np.sum((z - z[idx]) ** 2, axis=1))
        nearest = np.minimum(nearest, d)

    return {
        "coverage_mean_nearest_distance": float(np.mean(nearest)),
        "coverage_p95_nearest_distance": float(np.percentile(nearest, 95)),
        "coverage_worst_nearest_distance": float(np.max(nearest)),
    }


def parse_args():
    p = argparse.ArgumentParser(
        description="Select ngspice candidates that maximize geometric design-space coverage."
    )
    p.add_argument("--input", required=True, type=Path, help="Input design-space CSV")
    p.add_argument("--output", required=True, type=Path, help="Selected candidate CSV")
    p.add_argument(
        "--topology",
        choices=sorted(PRESETS),
        help="Topology preset. Not needed if --columns is supplied.",
    )
    p.add_argument(
        "--columns",
        nargs="+",
        help="Important dimensions. May be exact CSV names or shorthands such as W1 W3 W6.",
    )
    p.add_argument("--count", type=int, default=100, help="Number of candidates")
    p.add_argument(
        "--status-column",
        help="Optional exact status column. PASS-like rows are selected automatically.",
    )
    p.add_argument(
        "--include-all",
        action="store_true",
        help="Do not filter PASS/FEASIBLE rows; consider every row.",
    )
    p.add_argument(
        "--selected-index-output",
        type=Path,
        help="Optional text file containing original CSV row indices.",
    )
    return p.parse_args()


def main():
    args = parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file does not exist: {args.input}")

    if args.count <= 0:
        raise SystemExit("--count must be > 0")

    requested = args.columns
    if requested is None:
        if args.topology is None:
            raise SystemExit("Supply either --topology or --columns")
        requested = PRESETS[args.topology]

    df = pd.read_csv(args.input)
    if df.empty:
        raise SystemExit(f"Input CSV is empty: {args.input}")

    work, used_status = eligible_rows(
        df, status_column=args.status_column, include_all=args.include_all
    )

    resolved = [resolve_column(work, c) for c in requested]

    # Preserve original CSV dataframe index for traceability.
    work = work.copy()
    work["_openams_source_row"] = work.index.astype(int)

    finite_work, numeric, finite_mask = finite_numeric_frame(work, resolved)

    if finite_work.empty:
        raise SystemExit(
            "No eligible rows have finite numeric values in all important columns: "
            + ", ".join(resolved)
        )

    x = numeric.to_numpy(dtype=float)
    z, lo, hi = normalize_unit_cube(x)

    count = min(args.count, len(finite_work))
    chosen_local, spacing_scores = farthest_point_sample(z, count)
    chosen = finite_work.iloc[chosen_local].copy()

    chosen.insert(0, "selection_rank", np.arange(1, len(chosen) + 1))
    chosen.insert(
        1,
        "selection_spacing_score",
        spacing_scores,
    )

    # Add normalized coordinates to make the coverage choice auditable.
    for j, col in enumerate(resolved):
        safe = normalized_name(col)
        chosen[f"selection_norm_{safe}"] = z[chosen_local, j]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    chosen.to_csv(args.output, index=False)

    if args.selected_index_output:
        args.selected_index_output.parent.mkdir(parents=True, exist_ok=True)
        with args.selected_index_output.open("w") as f:
            for src_idx in chosen["_openams_source_row"].astype(int):
                f.write(f"{src_idx}\n")

    summary = coverage_summary(z, chosen_local)

    print("===== OPENAMS SPICE CANDIDATE SELECTION =====")
    print(f"input:                       {args.input}")
    print(f"input rows:                  {len(df)}")
    if used_status:
        print(f"status filter:               {used_status} -> PASS/FEASIBLE")
    else:
        print("status filter:               none")
    print(f"eligible finite rows:        {len(finite_work)}")
    print(f"selected candidates:         {len(chosen)}")
    print(f"important columns:           {', '.join(resolved)}")
    print(f"output:                      {args.output}")
    print()
    print("dimension ranges:")
    for col, a, b in zip(resolved, lo, hi):
        print(f"  {col:<28} min={a:.12g} max={b:.12g}")
    print()
    print("coverage in normalized important-variable space:")
    print(
        f"  mean nearest selected distance: {summary['coverage_mean_nearest_distance']:.6f}"
    )
    print(
        f"  p95 nearest selected distance:  {summary['coverage_p95_nearest_distance']:.6f}"
    )
    print(
        f"  worst nearest selected distance:{summary['coverage_worst_nearest_distance']:.6f}"
    )


if __name__ == "__main__":
    main()

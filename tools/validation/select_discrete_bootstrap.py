#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_FEATURES = [
    "w_m1_um",
    "w_m2_um",
    "w_m3_um",
    "w_m4_um",
    "w_m5_um",
    "w_m6_um",
    "w_m7_um",
    "vbias_v",
    "vout_v",
]


def effective_features(df, requested):
    """
    Remove:
      1. constant dimensions
      2. exact duplicate dimensions
    """
    kept = []
    removed = []

    for col in requested:
        if col not in df.columns:
            raise ValueError(f"missing feature: {col}")

        values = df[col].to_numpy(dtype=float)

        if np.allclose(values, values[0], rtol=0.0, atol=1e-12):
            removed.append((col, "constant"))
            continue

        duplicate_of = None
        for prev in kept:
            p = df[prev].to_numpy(dtype=float)
            if np.allclose(values, p, rtol=0.0, atol=1e-12):
                duplicate_of = prev
                break

        if duplicate_of is not None:
            removed.append((col, f"duplicate of {duplicate_of}"))
            continue

        kept.append(col)

    return kept, removed


def normalize(x):
    lo = np.min(x, axis=0)
    hi = np.max(x, axis=0)
    span = hi - lo

    if np.any(span <= 0):
        raise ValueError("constant dimensions survived feature filtering")

    return (x - lo) / span


def farthest_point_sample(x, count):
    """
    Deterministic maximin bootstrap.

    Start near the center of the normalized feasible cloud,
    then repeatedly select the point whose nearest selected
    neighbor is farthest away.
    """
    n = len(x)

    if count > n:
        raise ValueError(f"requested {count} points from pool of {n}")

    center = np.full(x.shape[1], 0.5)

    first = int(np.argmin(np.sum((x - center) ** 2, axis=1)))

    selected = [first]

    min_dist2 = np.sum((x - x[first]) ** 2, axis=1)
    min_dist2[first] = -1.0

    while len(selected) < count:
        nxt = int(np.argmax(min_dist2))
        selected.append(nxt)

        d2 = np.sum((x - x[nxt]) ** 2, axis=1)
        min_dist2 = np.minimum(min_dist2, d2)

        min_dist2[selected] = -1.0

    return selected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--count", type=int, default=16)
    ap.add_argument("--features", nargs="+", default=DEFAULT_FEATURES)
    args = ap.parse_args()

    df = pd.read_csv(args.pool)

    if "candidate_id" not in df.columns:
        raise SystemExit("pool must contain candidate_id")

    features, removed = effective_features(df, args.features)

    if not features:
        raise SystemExit("no varying optimizer features remain")

    x = df[features].to_numpy(dtype=float)
    xn = normalize(x)

    indices = farthest_point_sample(xn, args.count)

    out = df.iloc[indices].copy().reset_index(drop=True)
    out.insert(0, "bootstrap_order", np.arange(len(out)))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False)

    print("===== DISCRETE FA-BO BOOTSTRAP =====")
    print(f"candidate pool          : {len(df)}")
    print(f"requested features      : {len(args.features)}")
    print(f"effective dimensions    : {len(features)}")
    print(f"effective features      : {', '.join(features)}")

    if removed:
        print("removed dimensions:")
        for col, reason in removed:
            print(f"  {col:<16} {reason}")

    print(f"selected candidates     : {len(out)}")
    print(f"output                  : {output}")

    print()
    print("===== SELECTED CANDIDATES =====")
    cols = ["bootstrap_order", "candidate_id", *features]
    print(out[cols].to_string(index=False))


if __name__ == "__main__":
    main()

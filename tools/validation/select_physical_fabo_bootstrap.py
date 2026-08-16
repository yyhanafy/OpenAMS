#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_FEATURES = [
    "nf_m1",
    "nf_m2",
    "nf_m3",
    "nf_m4",
    "nf_m5",
    "nf_m6",
    "nf_m7",
    "vbias_v",
]


def reduce_features(df, features):
    kept = []
    removed = []

    for col in features:
        x = df[col].to_numpy(dtype=float)

        if np.allclose(x, x[0], atol=1e-12, rtol=0):
            removed.append((col, "constant"))
            continue

        duplicate = None
        for prev in kept:
            y = df[prev].to_numpy(dtype=float)
            if np.allclose(x, y, atol=1e-12, rtol=0):
                duplicate = prev
                break

        if duplicate:
            removed.append((col, f"duplicate of {duplicate}"))
        else:
            kept.append(col)

    return kept, removed


def normalize(x):
    lo = x.min(axis=0)
    hi = x.max(axis=0)
    return (x - lo) / (hi - lo)


def maximin(x, count):
    if count > len(x):
        raise ValueError("count exceeds pool size")

    # Start closest to center.
    center = np.full(x.shape[1], 0.5)
    first = int(np.argmin(np.sum((x - center) ** 2, axis=1)))

    selected = [first]

    nearest_d2 = np.sum((x - x[first]) ** 2, axis=1)
    nearest_d2[first] = -1

    while len(selected) < count:
        nxt = int(np.argmax(nearest_d2))
        selected.append(nxt)

        d2 = np.sum((x - x[nxt]) ** 2, axis=1)
        nearest_d2 = np.minimum(nearest_d2, d2)
        nearest_d2[selected] = -1

    return selected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--count", type=int, default=16)
    ap.add_argument("--features", nargs="+", default=DEFAULT_FEATURES)
    args = ap.parse_args()

    df = pd.read_csv(args.pool)

    if "physical_candidate_id" not in df.columns:
        raise SystemExit("missing physical_candidate_id")

    features, removed = reduce_features(df, args.features)

    if not features:
        raise SystemExit("no varying physical dimensions")

    x = df[features].to_numpy(dtype=float)
    xn = normalize(x)

    selected = maximin(xn, args.count)

    out = df.iloc[selected].copy().reset_index(drop=True)
    out.insert(0, "bootstrap_order", range(len(out)))

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)

    print("===== PHYSICAL FA-BO BOOTSTRAP =====")
    print(f"physical pool          : {len(df)}")
    print(f"requested dimensions   : {len(args.features)}")
    print(f"effective dimensions   : {len(features)}")
    print(f"effective features     : {', '.join(features)}")

    if removed:
        print("removed dimensions:")
        for col, why in removed:
            print(f"  {col:<12} {why}")

    print(f"selected candidates    : {len(out)}")
    print(f"output                 : {path}")

    print()
    print("===== SELECTED PHYSICAL CANDIDATES =====")

    cols = [
        "bootstrap_order",
        "physical_candidate_id",
        "source_candidate_id",
        *features,
        "max_width_rel_error",
    ]

    print(out[cols].to_string(index=False))


if __name__ == "__main__":
    main()

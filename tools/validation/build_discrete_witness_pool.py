#!/usr/bin/env python3

import argparse
from pathlib import Path

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--witnesses", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--features", nargs="+", default=DEFAULT_FEATURES)
    args = ap.parse_args()

    df = pd.read_csv(args.witnesses)

    missing = [c for c in args.features if c not in df.columns]
    if missing:
        raise SystemExit(f"missing feature columns: {missing}")

    # Only exact valid Step-5 witnesses are allowed into the pool.
    if "exact_device_pass" in df.columns:
        df = df[df["exact_device_pass"] == 1]

    if "all_saturated" in df.columns:
        df = df[df["all_saturated"] == 1]

    df = df.reset_index(drop=True)

    # Preserve only optimizer-facing information.
    keep = []

    for c in [
        "independent_point_index",
        "witness_rank",
        *args.features,
    ]:
        if c in df.columns and c not in keep:
            keep.append(c)

    pool = df[keep].copy()

    # Remove electrically identical optimizer candidates.
    before = len(pool)
    pool = pool.drop_duplicates(subset=args.features).reset_index(drop=True)

    # Stable discrete candidate identifier.
    pool.insert(
        0,
        "candidate_id",
        [f"witness_{i:08d}" for i in range(len(pool))],
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pool.to_csv(output, index=False)

    print("===== DISCRETE WITNESS POOL =====")
    print(f"input rows             : {len(df)}")
    print(f"unique candidates      : {len(pool)}")
    print(f"duplicates removed     : {before - len(pool)}")
    print(f"optimizer dimensions   : {len(args.features)}")
    print(f"features               : {', '.join(args.features)}")
    print(f"output                 : {output}")


if __name__ == "__main__":
    main()

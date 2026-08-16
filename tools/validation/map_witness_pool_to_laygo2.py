#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


# Physical characterization from native Laygo2 -> Magic -> SPICE:
#
# NMOS nf=2:
#   two devices, each W=0.5um L=0.15um
#   => effective W = 0.5 * nf
#
# PMOS nf=2:
#   two devices, each W=1.0um L=0.15um
#   => effective W = 1.0 * nf
#
DEVICE_TYPES = {
    1: "nmos",
    2: "nmos",
    3: "pmos",
    4: "pmos",
    5: "nmos",
    6: "pmos",
    7: "nmos",
}

FINGER_WIDTH_UM = {
    "nmos": 0.5,
    "pmos": 1.0,
}


def nearest_nf(width_um, finger_width_um):
    return int(np.floor(width_um / finger_width_um + 0.5))


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--pool", required=True)
    ap.add_argument("--output", required=True)

    ap.add_argument("--rejected-output")
    ap.add_argument("--nf-min", type=int, default=2)
    ap.add_argument("--nf-max", type=int, default=128)

    args = ap.parse_args()

    df = pd.read_csv(args.pool)

    required = [
        "candidate_id",
        "vbias_v",
        "vout_v",
        *[f"w_m{i}_um" for i in range(1, 8)],
    ]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SystemExit(f"missing columns: {missing}")

    out = df.copy()

    legal = np.ones(len(out), dtype=bool)

    for i in range(1, 8):
        devtype = DEVICE_TYPES[i]
        fw = FINGER_WIDTH_UM[devtype]

        requested = out[f"w_m{i}_um"].to_numpy(dtype=float)

        nf = np.floor(requested / fw + 0.5).astype(int)
        realized = nf.astype(float) * fw

        abs_error = realized - requested
        rel_error = np.abs(abs_error) / requested

        out[f"nf_m{i}"] = nf
        out[f"realized_w_m{i}_um"] = realized
        out[f"width_error_m{i}_um"] = abs_error
        out[f"width_rel_error_m{i}"] = rel_error

        legal &= (nf >= args.nf_min) & (nf <= args.nf_max)

    out["laygo2_legal"] = legal

    rejected = out.loc[~legal].copy()
    physical = out.loc[legal].copy()

    #
    # One post-layout circuit is uniquely determined by
    # physical device geometry + externally imposed bias.
    #
    # vout_v is NOT part of this key because post-layout SPICE
    # solves V(out); it is witness metadata only.
    #
    physical_key = [
        *[f"nf_m{i}" for i in range(1, 8)],
        "vbias_v",
    ]

    physical = physical.sort_values(
        ["candidate_id"]
    ).reset_index(drop=True)

    before_dedup = len(physical)

    physical["source_candidate_id"] = physical["candidate_id"]

    physical = (
        physical
        .drop_duplicates(subset=physical_key, keep="first")
        .reset_index(drop=True)
    )

    physical.insert(
        0,
        "physical_candidate_id",
        [f"physical_{i:08d}" for i in range(len(physical))]
    )

    #
    # Overall quantization statistics.
    #
    rel_cols = [
        f"width_rel_error_m{i}"
        for i in range(1, 8)
    ]

    physical["max_width_rel_error"] = (
        physical[rel_cols].max(axis=1)
    )

    physical["mean_width_rel_error"] = (
        physical[rel_cols].mean(axis=1)
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    physical.to_csv(output, index=False)

    if args.rejected_output:
        rp = Path(args.rejected_output)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rejected.to_csv(rp, index=False)

    print("===== LAYGO2 PHYSICAL WITNESS POOL =====")
    print(f"input electrical witnesses : {len(df)}")
    print(f"Laygo2 legal witnesses      : {int(legal.sum())}")
    print(f"Laygo2 rejected witnesses   : {int((~legal).sum())}")
    print()
    print(f"before physical dedup       : {before_dedup}")
    print(f"unique physical candidates  : {len(physical)}")
    print(
        f"physical duplicates removed : "
        f"{before_dedup - len(physical)}"
    )

    print()
    print("native transistor mapping:")
    print("  NMOS: L=0.15um, W=0.5um * nf")
    print("  PMOS: L=0.15um, W=1.0um * nf")
    print(
        f"  legal nf: {args.nf_min}..{args.nf_max}"
    )

    print()
    print("quantization error among unique physical candidates:")
    print(
        f"  mean of mean relative error : "
        f"{100*physical['mean_width_rel_error'].mean():.4f}%"
    )
    print(
        f"  median max relative error   : "
        f"{100*physical['max_width_rel_error'].median():.4f}%"
    )
    print(
        f"  worst max relative error    : "
        f"{100*physical['max_width_rel_error'].max():.4f}%"
    )

    print()
    print(f"output: {output}")

    if args.rejected_output:
        print(f"rejected: {args.rejected_output}")

    print()
    print("===== FIRST 10 PHYSICAL CANDIDATES =====")

    cols = [
        "physical_candidate_id",
        "source_candidate_id",
        *[f"nf_m{i}" for i in range(1, 8)],
        "vbias_v",
        "vout_v",
        "max_width_rel_error",
    ]

    print(
        physical[cols]
        .head(10)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

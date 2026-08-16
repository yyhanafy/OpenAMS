#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import pandas as pd


WIDTH_COLUMNS = [
    "w_m1_um",
    "w_m2_um",
    "w_m3_um",
    "w_m4_um",
    "w_m5_um",
    "w_m6_um",
    "w_m7_um",
]


def select_candidate(pool, candidate_id):
    row = pool[pool["candidate_id"] == candidate_id]

    if len(row) != 1:
        raise SystemExit(
            f"candidate_id {candidate_id!r} matched {len(row)} rows"
        )

    return row.iloc[0]


def select_next_pending(pool, observations):
    pending = observations[
        observations["spice_status"].astype(str).str.upper() == "PENDING"
    ]

    if len(pending) == 0:
        raise SystemExit("no pending candidates remain")

    # Preserve bootstrap order.
    pending = pending.sort_values("bootstrap_order")
    candidate_id = str(pending.iloc[0]["candidate_id"])

    return select_candidate(pool, candidate_id)


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--pool", required=True)

    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidate-id")
    group.add_argument("--next-pending", action="store_true")

    ap.add_argument("--observations")
    ap.add_argument("--output-dir", required=True)

    args = ap.parse_args()

    pool = pd.read_csv(args.pool)

    if args.next_pending:
        if not args.observations:
            raise SystemExit(
                "--observations is required with --next-pending"
            )

        observations = pd.read_csv(args.observations)
        row = select_next_pending(pool, observations)

    else:
        row = select_candidate(pool, args.candidate_id)

    candidate_id = str(row["candidate_id"])

    outdir = Path(args.output_dir) / candidate_id
    outdir.mkdir(parents=True, exist_ok=True)

    widths = {
        c: float(row[c])
        for c in WIDTH_COLUMNS
    }

    data = {
        "candidate_id": candidate_id,

        "implementation_parameters": {
            **widths,
            "vbias_v": float(row["vbias_v"]),
        },

        # These are witness-state references.
        # They are NOT forced during post-layout evaluation.
        "witness_reference": {
            "vout_v": float(row["vout_v"]),
            "independent_point_index": int(
                row["independent_point_index"]
            ),
            "witness_rank": int(row["witness_rank"]),
        },
    }

    json_path = outdir / "candidate.json"

    with json_path.open("w") as f:
        json.dump(data, f, indent=2)

    #
    # SPICE parameter include.
    #
    # Widths are converted from numeric micrometers in the
    # witness database into SPICE physical dimensions here.
    #
    inc_path = outdir / "candidate_params.inc"

    with inc_path.open("w") as f:
        f.write(f"* OpenAMS FA-BO candidate: {candidate_id}\n")
        f.write(
            f"* witness reference vout = "
            f"{float(row['vout_v']):.12g} V\n"
        )
        f.write("* vout is NOT forced by this include file\n\n")

        for i in range(1, 8):
            value = float(row[f"w_m{i}_um"])
            f.write(
                f".param W_M{i}={value:.12g}u\n"
            )

        f.write(
            f".param VBIAS={float(row['vbias_v']):.12g}\n"
        )

    print("===== MATERIALIZED FA-BO CANDIDATE =====")
    print(f"candidate_id   : {candidate_id}")
    print(f"output dir     : {outdir}")
    print()

    for i in range(1, 8):
        print(
            f"W{i:<2}            : "
            f"{float(row[f'w_m{i}_um']):.9f} um"
        )

    print(f"VBIAS          : {float(row['vbias_v']):.9f} V")
    print()
    print(
        f"witness VOUT   : {float(row['vout_v']):.9f} V "
        "(reference only)"
    )
    print()
    print(f"json           : {json_path}")
    print(f"spice params   : {inc_path}")


if __name__ == "__main__":
    main()

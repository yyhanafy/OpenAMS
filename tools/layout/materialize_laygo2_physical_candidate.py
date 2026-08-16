#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--candidate-id", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.pool)

    row = df.loc[
        df["physical_candidate_id"] == args.candidate_id
    ]

    if len(row) != 1:
        raise SystemExit(
            f"{args.candidate_id}: expected 1 row, got {len(row)}"
        )

    r = row.iloc[0]

    devices = {
        "M1": {"type": "nmos", "nf": int(r["nf_m1"])},
        "M2": {"type": "nmos", "nf": int(r["nf_m2"])},
        "M3": {"type": "pmos", "nf": int(r["nf_m3"])},
        "M4": {"type": "pmos", "nf": int(r["nf_m4"])},
        "M5": {"type": "nmos", "nf": int(r["nf_m5"])},
        "M6": {"type": "pmos", "nf": int(r["nf_m6"])},
        "M7": {"type": "nmos", "nf": int(r["nf_m7"])},
    }

    data = {
        "physical_candidate_id": str(r["physical_candidate_id"]),
        "source_candidate_id": str(r["source_candidate_id"]),
        "vbias_v": float(r["vbias_v"]),
        "witness_vout_v": float(r["vout_v"]),
        "devices": devices,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2))

    print("===== LAYGO2 PHYSICAL CANDIDATE =====")
    print("physical_candidate_id :", data["physical_candidate_id"])
    print("source_candidate_id   :", data["source_candidate_id"])
    print("vbias_v               :", data["vbias_v"])
    print()

    for name, spec in devices.items():
        print(
            f"{name:<3} {spec['type']:<4} "
            f"nf={spec['nf']}"
        )

    print()
    print("output:", out)


if __name__ == "__main__":
    main()

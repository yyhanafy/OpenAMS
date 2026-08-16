#!/usr/bin/env python3

import argparse
from pathlib import Path

import pandas as pd


RESULT_COLUMNS = [
    "candidate_id",
    "bootstrap_order",

    "layout_status",
    "pex_status",
    "spice_status",

    "gain_db",
    "ugb_hz",
    "phase_margin_deg",
    "power_w",
    "area_um2",

    "spec_pass",
    "objective_value",

    "failure_reason",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    candidates = pd.read_csv(args.candidates)

    required = ["candidate_id", "bootstrap_order"]
    missing = [c for c in required if c not in candidates.columns]
    if missing:
        raise SystemExit(f"missing columns: {missing}")

    out = pd.DataFrame({
        "candidate_id": candidates["candidate_id"],
        "bootstrap_order": candidates["bootstrap_order"],

        "layout_status": "PENDING",
        "pex_status": "PENDING",
        "spice_status": "PENDING",

        "gain_db": pd.NA,
        "ugb_hz": pd.NA,
        "phase_margin_deg": pd.NA,
        "power_w": pd.NA,
        "area_um2": pd.NA,

        "spec_pass": pd.NA,
        "objective_value": pd.NA,

        "failure_reason": pd.NA,
    })

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False)

    print("===== FA-BO OBSERVATION TABLE =====")
    print(f"candidates : {len(out)}")
    print(f"output     : {output}")
    print()
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()

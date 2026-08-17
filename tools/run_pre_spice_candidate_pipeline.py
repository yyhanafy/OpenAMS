#!/usr/bin/env python3
"""
Run the generic OpenAMS pre-SPICE candidate-selection stage end-to-end.

Pipeline
--------
valid_witnesses.csv
    ↓
estimate_pre_spice_metrics.py
    ↓
pre_spice_metrics.csv
    ↓
select_pre_spice_candidates.py
    ↓
ngspice_candidates.csv

Topology-specific knowledge is NOT encoded here. It comes from the compiled
contract's `pre_spice_metrics` metadata.

The script is therefore topology-agnostic and can be used for folded cascode,
two-stage op-amp, or any future topology whose compiled contract contains the
required metric metadata.

Example
-------
python tools/run_pre_spice_candidate_pipeline.py \
  --contract examples/folded_cascode/generated/assignment_synthesis/hierarchical_component_contract.json \
  --witnesses examples/folded_cascode/generated/assignment_synthesis/folded_valid_witnesses_L015_v2.csv \
  --technology-csv technology/sky130_tt_27c_mos_characterization.csv \
  --metrics-output examples/folded_cascode/generated/assignment_synthesis/folded_pre_spice_metrics_L015_v2.csv \
  --candidates-output examples/folded_cascode/generated/assignment_synthesis/folded_ngspice_candidates_100.csv \
  --count 100 \
  --metric est_gain_db:high:0:2 \
  --metric est_ugb_hz:high:0:2 \
  --metric est_power_w:max:0.0005:1 \
  --group-column independent_point_index \
  --max-per-group 3
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generic OpenAMS valid-witness → metric-estimation → "
            "pre-SPICE candidate-selection pipeline."
        )
    )

    p.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="OpenAMS repository root. Default: current directory.",
    )

    p.add_argument("--contract", required=True, type=Path)
    p.add_argument("--witnesses", required=True, type=Path)
    p.add_argument("--technology-csv", required=True, type=Path)

    p.add_argument(
        "--metrics-output",
        required=True,
        type=Path,
        help="Output CSV containing all witnesses plus estimated metrics.",
    )
    p.add_argument(
        "--candidates-output",
        required=True,
        type=Path,
        help="Output CSV containing selected pre-SPICE/ngspice candidates.",
    )

    p.add_argument("--count", type=int, default=100)

    p.add_argument(
        "--metric",
        action="append",
        default=[],
        help=(
            "Selection metric in the form "
            "COLUMN:DIRECTION:LIMIT[:WEIGHT[:SCALE]]. Repeat as needed."
        ),
    )

    p.add_argument(
        "--diversity-columns",
        nargs="+",
        default=None,
        help=(
            "Optional explicit diversity columns. If omitted, the selector "
            "auto-detects w_m*_um columns."
        ),
    )
    p.add_argument(
        "--extra-diversity-columns",
        nargs="*",
        default=[],
        help="Additional variables to add to the diversity space.",
    )

    p.add_argument("--group-column", default=None)
    p.add_argument("--max-per-group", type=int, default=3)
    p.add_argument("--eligible-column", default=None)

    p.add_argument("--exploit-fraction", type=float, default=0.50)
    p.add_argument("--boundary-fraction", type=float, default=0.20)
    p.add_argument("--diversity-fraction", type=float, default=0.30)

    p.add_argument(
        "--prefer-pass",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    p.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Reuse an existing --metrics-output CSV and only run selection.",
    )

    p.add_argument(
        "--estimator",
        type=Path,
        default=Path("tools/validation/estimate_pre_spice_metrics.py"),
        help="Generic metric estimator script.",
    )
    p.add_argument(
        "--selector",
        type=Path,
        default=Path("tools/validation/select_pre_spice_candidates.py"),
        help="Generic candidate selector script.",
    )

    return p.parse_args()


def resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def run(cmd: list[str], cwd: Path) -> None:
    print("\nRUN:")
    print("  " + " \\\n    ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> None:
    a = parse_args()
    root = a.root.resolve()

    if not root.is_dir():
        raise SystemExit(f"repository root does not exist: {root}")

    contract = resolve(root, a.contract)
    witnesses = resolve(root, a.witnesses)
    technology_csv = resolve(root, a.technology_csv)
    metrics_output = resolve(root, a.metrics_output)
    candidates_output = resolve(root, a.candidates_output)
    estimator = resolve(root, a.estimator)
    selector = resolve(root, a.selector)

    for p in (contract, witnesses, technology_csv, estimator, selector):
        if not p.is_file():
            raise SystemExit(f"missing required file: {p}")

    if not a.metric:
        raise SystemExit("at least one --metric is required")

    if a.count <= 0:
        raise SystemExit("--count must be > 0")

    metrics_output.parent.mkdir(parents=True, exist_ok=True)
    candidates_output.parent.mkdir(parents=True, exist_ok=True)

    print("===== OPENAMS GENERIC PRE-SPICE PIPELINE =====")
    print("contract          :", contract)
    print("witnesses         :", witnesses)
    print("technology CSV    :", technology_csv)
    print("metrics output    :", metrics_output)
    print("candidates output :", candidates_output)
    print("candidate count   :", a.count)

    # ---------------------------------------------------------------
    # Stage 1: Generic contract-driven metric estimation
    # ---------------------------------------------------------------
    if not a.skip_metrics:
        run(
            [
                sys.executable,
                str(estimator),
                "--contract",
                str(contract),
                "--witnesses",
                str(witnesses),
                "--technology-csv",
                str(technology_csv),
                "--output",
                str(metrics_output),
            ],
            cwd=root,
        )
    else:
        if not metrics_output.is_file():
            raise SystemExit(
                "--skip-metrics requested but metrics output does not exist: "
                f"{metrics_output}"
            )
        print("\nSKIP metric estimation; reusing:", metrics_output)

    # ---------------------------------------------------------------
    # Stage 2: Generic metric/spec + diversity candidate selection
    # ---------------------------------------------------------------
    cmd = [
        sys.executable,
        str(selector),
        "--input",
        str(metrics_output),
        "--output",
        str(candidates_output),
        "--count",
        str(a.count),
    ]

    for metric in a.metric:
        cmd += ["--metric", metric]

    if a.diversity_columns:
        cmd += ["--diversity-columns", *a.diversity_columns]

    if a.extra_diversity_columns:
        cmd += ["--extra-diversity-columns", *a.extra_diversity_columns]

    if a.group_column:
        cmd += ["--group-column", a.group_column]

    cmd += ["--max-per-group", str(a.max_per_group)]

    if a.eligible_column:
        cmd += ["--eligible-column", a.eligible_column]

    cmd += [
        "--exploit-fraction",
        str(a.exploit_fraction),
        "--boundary-fraction",
        str(a.boundary_fraction),
        "--diversity-fraction",
        str(a.diversity_fraction),
    ]

    cmd.append("--prefer-pass" if a.prefer_pass else "--no-prefer-pass")

    run(cmd, cwd=root)

    print("\n===== PRE-SPICE PIPELINE COMPLETE =====")
    print("valid witnesses       :", witnesses)
    print("all estimated metrics :", metrics_output)
    print("selected candidates   :", candidates_output)


if __name__ == "__main__":
    main()

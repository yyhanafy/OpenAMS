#!/usr/bin/env python3
"""Migrate the two-stage M1 independent width to total-width semantics."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--intent",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs/design_intent.yaml"),
    )
    parser.add_argument("--minimum-um", type=float, default=1.0)
    parser.add_argument("--maximum-um", type=float, default=300.0)
    args = parser.parse_args()

    data = yaml.safe_load(args.intent.read_text(encoding="utf-8"))
    variable = (
        data["synthesis_parameterization"]
        ["independent_variables"]
        ["w_m1_um"]
    )

    backup = args.intent.with_name(
        args.intent.name + ".before_total_width_step3"
    )
    if not backup.exists():
        shutil.copy2(args.intent, backup)

    variable["kind"] = "total_width"
    variable["minimum"] = args.minimum_um
    variable["maximum"] = args.maximum_um
    variable["sampling"] = "continuous_total_width_with_integer_nf"
    variable["finger_realization"] = {
        "enabled": True,
        "finger_width_min_um": 0.42,
        "finger_width_max_um": 100.0,
        "nf_min": 1,
        "scaling_model": "linear_current_scaling",
    }

    args.intent.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    print(f"[PASS] updated {args.intent}")
    print(f"[PASS] backup  {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def patch_two_stage(data):
    comps = {c["id"]: c for c in data["components"]}

    comps["input_bias_network"]["depends_on"] = []
    comps["output_stage"]["depends_on"] = ["input_bias_network"]

    # Legacy B exact-realizer builder expects these lineage aliases.
    comps["output_stage"]["exact_realizer"]["coverage_bindings"] = {
        "a_point_index": "source_point_index",
        "a_witness_rank": "source_witness_rank",
    }

    data["schema_version"] = max(int(data.get("schema_version", 0)), 4)
    return data


def patch_folded(data):
    comps = {c["id"]: c for c in data["components"]}

    # Execution/join order only.  The three MLP feasibility masks remain
    # independently evaluated before exact realization.
    comps["input_tail_network"]["depends_on"] = []
    comps["upper_folded_network"]["depends_on"] = ["input_tail_network"]
    comps["lower_output_network"]["depends_on"] = ["upper_folded_network"]

    data["schema_version"] = max(int(data.get("schema_version", 0)), 4)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--two-stage", type=Path)
    ap.add_argument("--folded", type=Path)
    args = ap.parse_args()

    if args.two_stage:
        save(args.two_stage, patch_two_stage(load(args.two_stage)))
        print("normalized two-stage:", args.two_stage)

    if args.folded:
        save(args.folded, patch_folded(load(args.folded)))
        print("normalized folded:", args.folded)


if __name__ == "__main__":
    main()

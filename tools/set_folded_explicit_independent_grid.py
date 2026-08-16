#!/usr/bin/env python3
from pathlib import Path
import argparse, yaml

ap = argparse.ArgumentParser()
ap.add_argument("--intent", type=Path, required=True)
a = ap.parse_args()

d = yaml.safe_load(a.intent.read_text())
hf = d["hierarchical_feasibility"]

hf["independent_point_source"] = {
    "kind": "explicit_grid",
    "variables": {
        "w_m1_um": {
            "kind": "total_width",
            "grid": {
                "minimum": 1.0,
                "maximum": 100.0,
                "count": 25,
                "spacing": "linear",
            },
        },
        "i_m3_a": {
            "kind": "current",
            "grid": {
                "minimum": 10.0e-6,
                "maximum": 100.0e-6,
                "count": 81,
                "spacing": "linear",
            },
        },
    },
}

a.intent.write_text(yaml.safe_dump(d, sort_keys=False))
print("updated:", a.intent)
print("independent grid: W1 1..100 um x25; I3 10..100 uA x81; total=2025")

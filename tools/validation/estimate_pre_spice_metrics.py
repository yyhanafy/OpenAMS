#!/usr/bin/env python3
"""
Generic contract-driven OpenAMS pre-SPICE metric estimator.

Topology-specific knowledge is declared under contract["pre_spice_metrics"].
This engine contains no transistor names, circuit-node names, topology names,
or fixed number of devices.

Contract schema (abridged)
--------------------------
"pre_spice_metrics": {
  "technology": {
    "length_um": 0.15,
    "neighbors": 8,
    "nmos_model_contains": "nfet",
    "pmos_model_contains": "pfet"
  },
  "constants": {
    "vdd": 1.8,
    "vicm": 0.9,
    "cl_f": 1e-11
  },
  "devices": {
    "M1": {
      "polarity": "nmos",
      "width": "w_m1_um",
      "vgs": "abs(vicm-tail_v)",
      "vds": "abs(psrc_left_v-tail_v)",
      "vbs": "abs(0-tail_v)"
    }
  },
  "metrics": [
    {"name": "est_gain_vv", "expression": "M1.gm * est_rout_ohm"},
    {"name": "est_gain_db", "expression": "db20(est_gain_vv)"}
  ]
}

Metric expressions are evaluated in listed order and may reference:
* witness columns
* constants
* device fields: gm, gds, ro, tech_distance
* previously evaluated metrics
* safe helper functions such as abs, min, max, sqrt, log, exp, db20, parallel

This estimator is for ranking/selection, not a substitute for ngspice.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

try:
    from scipy.spatial import cKDTree
except ImportError as exc:
    raise SystemExit("scipy is required for technology lookup") from exc


ALIASES = {
    "polarity": ["polarity", "device_polarity", "type"],
    "model": ["model", "model_name", "device_model"],
    "length_um": ["length_um", "l_um", "length"],
    "width_um": ["width_um", "w_um", "width"],
    "vgs_v": ["vgs_v", "vgs_abs_v", "vgs"],
    "vds_v": ["vds_v", "vds_abs_v", "vds"],
    "vbs_v": ["vbs_v", "vbs_abs_v", "vbs"],
    "gm_s": ["gm_s", "gm"],
    "gds_s": ["gds_s", "gds"],
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Generic contract-driven pre-SPICE metric estimator."
    )
    p.add_argument("--contract", required=True, type=Path)
    p.add_argument("--witnesses", required=True, type=Path)
    p.add_argument("--technology-csv", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    return p.parse_args()


def resolve_col(df, logical, required=True):
    for c in ALIASES[logical]:
        if c in df.columns:
            return c
    if required:
        raise KeyError(f"technology CSV lacks {logical}; tried {ALIASES[logical]}")
    return None


def numeric(s):
    return pd.to_numeric(s, errors="coerce")


class SmallSignalLookup:
    def __init__(
        self,
        tech,
        *,
        polarity,
        length_um,
        model_contains=None,
        k=8,
    ):
        self.polarity = str(polarity).lower()
        self.length_um = float(length_um)
        self.k = int(k)

        pc = resolve_col(tech, "polarity")
        lc = resolve_col(tech, "length_um")
        wc = resolve_col(tech, "width_um")
        vgsc = resolve_col(tech, "vgs_v")
        vdsc = resolve_col(tech, "vds_v")
        vbsc = resolve_col(tech, "vbs_v")
        gmc = resolve_col(tech, "gm_s")
        gdsc = resolve_col(tech, "gds_s")
        mc = resolve_col(tech, "model", required=False)

        x = tech.copy()
        pol = x[pc].astype(str).str.strip().str.lower()
        x = x[pol == self.polarity].copy()

        ll = numeric(x[lc])
        x = x[np.isclose(ll, self.length_um, atol=1e-9)].copy()

        if mc is not None and model_contains:
            mask = (
                x[mc].astype(str).str.lower()
                .str.contains(str(model_contains).lower(), regex=False)
            )
            if mask.any():
                x = x[mask].copy()

        if x.empty:
            raise RuntimeError(
                f"no technology rows for polarity={polarity}, L={length_um}"
            )

        work = pd.DataFrame(
            {
                "vgs": numeric(x[vgsc]).abs(),
                "vds": numeric(x[vdsc]).abs(),
                "vbs": numeric(x[vbsc]).abs(),
                "width": numeric(x[wc]).abs(),
                "gm": numeric(x[gmc]).abs(),
                "gds": numeric(x[gdsc]).abs(),
            }
        ).dropna()

        work = work[
            (work["width"] > 0) &
            (work["gm"] >= 0) &
            (work["gds"] >= 0)
        ].copy()

        work["gm_per_um"] = work["gm"] / work["width"]
        work["gds_per_um"] = work["gds"] / work["width"]

        grouped = (
            work.groupby(["vgs", "vds", "vbs"], as_index=False)
            [["gm_per_um", "gds_per_um"]]
            .median()
        )

        if grouped.empty:
            raise RuntimeError("technology lookup has zero usable rows")

        self.points = grouped[["vgs", "vds", "vbs"]].to_numpy(float)
        self.gm_per_um = grouped["gm_per_um"].to_numpy(float)
        self.gds_per_um = grouped["gds_per_um"].to_numpy(float)
        self.tree = cKDTree(self.points)

        print(
            f"technology {self.polarity}: "
            f"{len(work)} rows -> {len(grouped)} unique voltage points"
        )

    def query(self, vgs, vds, vbs, width_um):
        pts = np.column_stack(
            [np.abs(vgs), np.abs(vds), np.abs(vbs)]
        )
        k = min(self.k, len(self.points))
        dist, idx = self.tree.query(pts, k=k, workers=-1)

        if k == 1:
            dist = dist[:, None]
            idx = idx[:, None]

        weights = 1.0 / np.maximum(dist, 1e-9) ** 2
        weights /= weights.sum(axis=1, keepdims=True)

        gm_u = np.sum(weights * self.gm_per_um[idx], axis=1)
        gds_u = np.sum(weights * self.gds_per_um[idx], axis=1)

        gm = gm_u * width_um
        gds = gds_u * width_um
        return gm, gds, dist[:, 0]


def parallel(*args):
    vals = [np.maximum(np.asarray(x, dtype=float), 1e-30) for x in args]
    inv = np.zeros_like(vals[0], dtype=float)
    for x in vals:
        inv += 1.0 / x
    return 1.0 / np.maximum(inv, 1e-30)


def db20(x):
    return 20.0 * np.log10(np.maximum(np.abs(x), 1e-30))


SAFE_GLOBALS = {
    "__builtins__": {},
    "abs": np.abs,
    "min": np.minimum,
    "max": np.maximum,
    "sqrt": np.sqrt,
    "log": np.log,
    "log10": np.log10,
    "exp": np.exp,
    "pi": math.pi,
    "parallel": parallel,
    "db20": db20,
}


def eval_expr(expr, env):
    try:
        return eval(str(expr), SAFE_GLOBALS, env)
    except Exception as exc:
        raise RuntimeError(f"failed expression {expr!r}: {exc}") from exc


def as_array(value, n):
    a = np.asarray(value, dtype=float)
    if a.ndim == 0:
        return np.full(n, float(a), dtype=float)
    if len(a) != n:
        raise RuntimeError(
            f"expression returned length {len(a)}, expected {n}"
        )
    return a


def main():
    a = parse_args()

    for p in [a.contract, a.witnesses, a.technology_csv]:
        if not p.is_file():
            raise SystemExit(f"missing file: {p}")

    contract = json.loads(a.contract.read_text(encoding="utf-8"))
    meta = contract.get("pre_spice_metrics")
    if not isinstance(meta, dict):
        raise SystemExit(
            "contract does not contain pre_spice_metrics metadata"
        )

    df = pd.read_csv(a.witnesses)
    tech = pd.read_csv(a.technology_csv)
    n = len(df)

    print("witness rows:", n)

    technology = meta.get("technology", {})
    length_um = float(technology["length_um"])
    neighbors = int(technology.get("neighbors", 8))

    lookups = {}
    for pol in ("nmos", "pmos"):
        lookups[pol] = SmallSignalLookup(
            tech,
            polarity=pol,
            length_um=length_um,
            model_contains=technology.get(f"{pol}_model_contains"),
            k=neighbors,
        )

    env = {}
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().all():
            env[c] = s.to_numpy(float)

    for k, v in meta.get("constants", {}).items():
        env[k] = float(v)

    out = df.copy()
    devices = {}

    for name, spec in meta.get("devices", {}).items():
        pol = str(spec["polarity"]).lower()
        if pol not in lookups:
            raise RuntimeError(f"{name}: unsupported polarity {pol}")

        width = as_array(eval_expr(spec["width"], env), n)
        vgs = as_array(eval_expr(spec["vgs"], env), n)
        vds = as_array(eval_expr(spec["vds"], env), n)
        vbs = as_array(eval_expr(spec["vbs"], env), n)

        gm, gds, dist = lookups[pol].query(
            vgs, vds, vbs, width
        )
        ro = 1.0 / np.maximum(gds, 1e-30)

        dev = SimpleNamespace(
            width=width,
            vgs=vgs,
            vds=vds,
            vbs=vbs,
            gm=gm,
            gds=gds,
            ro=ro,
            tech_distance=dist,
        )
        devices[name] = dev
        env[name] = dev

        tag = str(name).lower()
        out[f"est_{tag}_gm_s"] = gm
        out[f"est_{tag}_gds_s"] = gds
        out[f"est_{tag}_ro_ohm"] = ro
        out[f"est_{tag}_tech_distance_v"] = dist

    # Generic aggregate device metrics.
    if devices:
        widths = np.zeros(n, dtype=float)
        dist_cols = []
        for name, dev in devices.items():
            widths += np.abs(dev.width)
            dist_cols.append(dev.tech_distance)

        out["est_total_width_um"] = widths
        out["est_gate_area_um2"] = length_um * widths
        stack = np.vstack(dist_cols)
        out["est_tech_distance_max_v"] = np.max(stack, axis=0)
        out["est_tech_distance_mean_v"] = np.mean(stack, axis=0)

        env["est_total_width_um"] = out["est_total_width_um"].to_numpy(float)
        env["est_gate_area_um2"] = out["est_gate_area_um2"].to_numpy(float)
        env["est_tech_distance_max_v"] = out[
            "est_tech_distance_max_v"
        ].to_numpy(float)
        env["est_tech_distance_mean_v"] = out[
            "est_tech_distance_mean_v"
        ].to_numpy(float)

    # Evaluate topology-declared metrics in order.
    metrics = meta.get("metrics", [])
    for spec in metrics:
        name = spec["name"]
        value = as_array(eval_expr(spec["expression"], env), n)
        out[name] = value
        env[name] = value

    # Optional generic ranks requested by metadata.
    for spec in meta.get("ranks", []):
        src = spec["source"]
        name = spec["name"]
        ascending = bool(spec.get("ascending", True))
        if src not in out.columns:
            raise RuntimeError(f"rank source not found: {src}")
        out[name] = (
            out[src]
            .rank(method="first", ascending=ascending)
            .astype(int)
        )

    a.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.output, index=False)

    print("\n===== GENERIC PRE-SPICE METRIC ESTIMATION =====")
    print("devices :", len(devices))
    print("metrics :", len(metrics))
    print("L (um)  :", length_um)
    print("output  :", a.output)

    metric_names = [m["name"] for m in metrics]
    if metric_names:
        print()
        print(
            out[metric_names]
            .describe(
                percentiles=[
                    .01, .05, .10, .25, .50,
                    .75, .90, .95, .99
                ]
            )
            .T.to_string()
        )


if __name__ == "__main__":
    main()

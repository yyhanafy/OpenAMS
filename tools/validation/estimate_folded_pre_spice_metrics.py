#!/usr/bin/env python3
"""
Estimate cheap pre-SPICE performance metrics for exact folded-cascode witnesses.

Purpose
-------
Rank/select exact hierarchical witnesses before ngspice.

Metrics
-------
1. DC gain (first-order ranking estimate):
       Gm ~= gm1
       Rout_p ~= ro7
       Rout_n ~= ro9 + ro11 + gm9*ro9*ro11
       Rout ~= Rout_p || Rout_n
       Av ~= Gm * Rout

2. Unity-gain bandwidth:
       UGB ~= gm1 / (2*pi*CL)

3. Power:
       P ~= VDD * (|I4| + |I5|)

4. Electrical gate-area proxy:
       Agate = L * sum(W1...W11)

gm/gds are obtained from the characterized dense technology table at the
witness DC operating point. Technology gm and gds are normalized by the
characterized width and rescaled to the requested witness width.

This is a ranking/selection estimator, not a substitute for ngspice.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from scipy.spatial import cKDTree
except ImportError as exc:
    raise SystemExit(
        "scipy is required for the technology lookup: "
        "python -m pip install scipy"
    ) from exc


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


def resolve_col(df: pd.DataFrame, logical: str, required=True):
    for c in ALIASES[logical]:
        if c in df.columns:
            return c
    if required:
        raise KeyError(
            f"technology CSV lacks {logical}; tried {ALIASES[logical]}"
        )
    return None


def numeric(s):
    return pd.to_numeric(s, errors="coerce")


class SmallSignalLookup:
    def __init__(
        self,
        tech: pd.DataFrame,
        *,
        polarity: str,
        length_um: float,
        model_contains: str | None,
        k: int = 8,
    ):
        self.polarity = polarity.lower()
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
                .str.contains(model_contains.lower(), regex=False)
            )
            if mask.any():
                x = x[mask].copy()

        if x.empty:
            raise RuntimeError(
                f"no technology rows for polarity={polarity}, L={length_um}"
            )

        work = pd.DataFrame({
            "vgs": numeric(x[vgsc]).abs(),
            "vds": numeric(x[vdsc]).abs(),
            "vbs": numeric(x[vbsc]).abs(),
            "width": numeric(x[wc]).abs(),
            "gm": numeric(x[gmc]).abs(),
            "gds": numeric(x[gdsc]).abs(),
        }).dropna()

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

        self.points = grouped[["vgs", "vds", "vbs"]].to_numpy(float)
        self.gm_per_um = grouped["gm_per_um"].to_numpy(float)
        self.gds_per_um = grouped["gds_per_um"].to_numpy(float)

        if len(grouped) == 0:
            raise RuntimeError("technology lookup has zero usable rows")

        self.tree = cKDTree(self.points)

        print(
            f"technology {self.polarity}: "
            f"{len(work)} rows -> {len(grouped)} unique voltage points"
        )

    def query(self, vgs, vds, vbs, width_um):
        pts = np.column_stack([
            np.abs(vgs),
            np.abs(vds),
            np.abs(vbs),
        ])

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
        nearest_distance = dist[:, 0]

        return gm, gds, nearest_distance


def require(df, names):
    missing = [x for x in names if x not in df.columns]
    if missing:
        raise RuntimeError(
            "witness CSV missing required fields: " + ", ".join(missing)
        )


def arr(df, name):
    return numeric(df[name]).to_numpy(float)


def device_operating_points(df, vdd, vicm):
    tail = arr(df, "tail_v")
    psrc_left = arr(df, "psrc_left_v")
    psrc_right = arr(df, "psrc_right_v")
    vnb1 = arr(df, "vnb1_v")
    vpb1 = arr(df, "vpb1_v")
    vpb2 = arr(df, "vpb2_v")
    x = arr(df, "x_v")
    vout = arr(df, "vout_v")
    vnb2 = arr(df, "vnb2_v")
    nsink_left = arr(df, "nsink_left_v")
    nsink_right = arr(df, "nsink_right_v")

    z = np.zeros(len(df))

    return {
        "M1": {
            "polarity": "nmos",
            "w": arr(df, "w_m1_um"),
            "vgs": np.abs(vicm - tail),
            "vds": np.abs(psrc_left - tail),
            "vbs": np.abs(z - tail),
        },
        "M2": {
            "polarity": "nmos",
            "w": arr(df, "w_m2_um"),
            "vgs": np.abs(vicm - tail),
            "vds": np.abs(psrc_right - tail),
            "vbs": np.abs(z - tail),
        },
        "M3": {
            "polarity": "nmos",
            "w": arr(df, "w_m3_um"),
            "vgs": np.abs(vnb1),
            "vds": np.abs(tail),
            "vbs": z,
        },
        "M4": {
            "polarity": "pmos",
            "w": arr(df, "w_m4_um"),
            "vgs": np.abs(vdd - vpb1),
            "vds": np.abs(vdd - psrc_left),
            "vbs": z,
        },
        "M5": {
            "polarity": "pmos",
            "w": arr(df, "w_m5_um"),
            "vgs": np.abs(vdd - vpb1),
            "vds": np.abs(vdd - psrc_right),
            "vbs": z,
        },
        "M6": {
            "polarity": "pmos",
            "w": arr(df, "w_m6_um"),
            "vgs": np.abs(vdd - vpb2),
            "vds": np.abs(psrc_left - x),
            "vbs": np.abs(vdd - psrc_left),
        },
        "M7": {
            "polarity": "pmos",
            "w": arr(df, "w_m7_um"),
            "vgs": np.abs(vdd - vpb2),
            "vds": np.abs(psrc_right - vout),
            "vbs": np.abs(vdd - psrc_right),
        },
        "M8": {
            "polarity": "nmos",
            "w": arr(df, "w_m8_um"),
            "vgs": np.abs(vnb2 - nsink_left),
            "vds": np.abs(x - nsink_left),
            "vbs": np.abs(nsink_left),
        },
        "M9": {
            "polarity": "nmos",
            "w": arr(df, "w_m9_um"),
            "vgs": np.abs(vnb2 - nsink_right),
            "vds": np.abs(vout - nsink_right),
            "vbs": np.abs(nsink_right),
        },
        "M10": {
            "polarity": "nmos",
            "w": arr(df, "w_m10_um"),
            "vgs": np.abs(x),
            "vds": np.abs(nsink_left),
            "vbs": z,
        },
        "M11": {
            "polarity": "nmos",
            "w": arr(df, "w_m11_um"),
            "vgs": np.abs(x),
            "vds": np.abs(nsink_right),
            "vbs": z,
        },
    }


def parse_args():
    p = argparse.ArgumentParser(
        description="Estimate pre-SPICE metrics for folded-cascode witnesses."
    )

    p.add_argument("--witnesses", type=Path, required=True)
    p.add_argument("--technology-csv", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)

    p.add_argument("--length-um", type=float, default=0.5)
    p.add_argument("--vdd", type=float, default=1.8)
    p.add_argument("--vicm", type=float, default=0.9)
    p.add_argument("--cl-pf", type=float, default=10.0)
    p.add_argument("--neighbors", type=int, default=8)

    p.add_argument("--nmos-model-contains", default="nfet")
    p.add_argument("--pmos-model-contains", default="pfet")

    # Optional selection thresholds. If omitted, only estimation/ranking is done.
    p.add_argument("--min-gain-db", type=float)
    p.add_argument("--min-ugb-hz", type=float)
    p.add_argument("--max-power-w", type=float)
    p.add_argument("--max-tech-distance-v", type=float)

    p.add_argument("--select", type=int, default=0)
    p.add_argument("--selected-output", type=Path)

    return p.parse_args()


def main():
    a = parse_args()

    if not a.witnesses.is_file():
        raise SystemExit(f"missing witnesses: {a.witnesses}")
    if not a.technology_csv.is_file():
        raise SystemExit(f"missing technology CSV: {a.technology_csv}")

    print("loading witnesses...")
    df = pd.read_csv(a.witnesses)

    required = [
        *(f"w_m{i}_um" for i in range(1, 12)),
        *(f"i_m{i}_a" for i in range(1, 12)),
        "tail_v", "vnb1_v",
        "psrc_left_v", "psrc_right_v",
        "vpb1_v", "vpb2_v",
        "x_v", "vout_v",
        "nsink_left_v", "nsink_right_v",
        "vnb2_v",
    ]
    require(df, required)

    print("witness rows:", len(df))

    print("loading technology CSV...")
    tech = pd.read_csv(a.technology_csv)

    nmos = SmallSignalLookup(
        tech,
        polarity="nmos",
        length_um=a.length_um,
        model_contains=a.nmos_model_contains,
        k=a.neighbors,
    )

    pmos = SmallSignalLookup(
        tech,
        polarity="pmos",
        length_um=a.length_um,
        model_contains=a.pmos_model_contains,
        k=a.neighbors,
    )

    ops = device_operating_points(df, vdd=a.vdd, vicm=a.vicm)
    out = df.copy()

    print("querying device small-signal parameters...")

    for name, spec in ops.items():
        lookup = nmos if spec["polarity"] == "nmos" else pmos

        gm, gds, dist = lookup.query(
            spec["vgs"], spec["vds"], spec["vbs"], spec["w"]
        )

        tag = name.lower()
        out[f"est_{tag}_gm_s"] = gm
        out[f"est_{tag}_gds_s"] = gds
        out[f"est_{tag}_ro_ohm"] = 1.0 / np.maximum(gds, 1e-30)
        out[f"est_{tag}_tech_distance_v"] = dist

    # Gain estimate
    gm1 = out["est_m1_gm_s"].to_numpy(float)

    ro7 = out["est_m7_ro_ohm"].to_numpy(float)
    ro9 = out["est_m9_ro_ohm"].to_numpy(float)
    ro11 = out["est_m11_ro_ohm"].to_numpy(float)
    gm9 = out["est_m9_gm_s"].to_numpy(float)

    rout_p = ro7
    rout_n = ro9 + ro11 + gm9 * ro9 * ro11

    rout = 1.0 / (
        1.0 / np.maximum(rout_p, 1e-30) +
        1.0 / np.maximum(rout_n, 1e-30)
    )

    gain_vv = gm1 * rout

    out["est_rout_p_ohm"] = rout_p
    out["est_rout_n_ohm"] = rout_n
    out["est_rout_ohm"] = rout
    out["est_gain_vv"] = gain_vv
    out["est_gain_db"] = 20.0 * np.log10(
        np.maximum(np.abs(gain_vv), 1e-30)
    )

    # UGB estimate
    cl_f = a.cl_pf * 1e-12
    out["est_ugb_hz"] = gm1 / (2.0 * math.pi * cl_f)

    # Power estimate
    i4 = np.abs(arr(out, "i_m4_a"))
    i5 = np.abs(arr(out, "i_m5_a"))
    out["est_idd_a"] = i4 + i5
    out["est_power_w"] = a.vdd * out["est_idd_a"]

    # Gate-area proxy
    widths = np.zeros(len(out), dtype=float)
    for i in range(1, 12):
        widths += np.abs(arr(out, f"w_m{i}_um"))

    out["est_total_width_um"] = widths
    out["est_gate_area_um2"] = a.length_um * widths

    # Technology lookup quality
    dcols = [f"est_m{i}_tech_distance_v" for i in range(1, 12)]
    out["est_tech_distance_max_v"] = out[dcols].max(axis=1)
    out["est_tech_distance_mean_v"] = out[dcols].mean(axis=1)

    # Ranking helpers
    out["rank_est_gain"] = (
        out["est_gain_db"].rank(method="first", ascending=False).astype(int)
    )
    out["rank_est_ugb"] = (
        out["est_ugb_hz"].rank(method="first", ascending=False).astype(int)
    )
    out["rank_low_power"] = (
        out["est_power_w"].rank(method="first", ascending=True).astype(int)
    )
    out["rank_low_area"] = (
        out["est_gate_area_um2"].rank(method="first", ascending=True).astype(int)
    )
    out["rank_low_tech_distance"] = (
        out["est_tech_distance_max_v"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    # Optional pre-SPICE pass flags
    mask = np.ones(len(out), dtype=bool)

    if a.min_gain_db is not None:
        out["est_gain_pass"] = out["est_gain_db"] >= a.min_gain_db
        mask &= out["est_gain_pass"].to_numpy(bool)

    if a.min_ugb_hz is not None:
        out["est_ugb_pass"] = out["est_ugb_hz"] >= a.min_ugb_hz
        mask &= out["est_ugb_pass"].to_numpy(bool)

    if a.max_power_w is not None:
        out["est_power_pass"] = out["est_power_w"] <= a.max_power_w
        mask &= out["est_power_pass"].to_numpy(bool)

    if a.max_tech_distance_v is not None:
        out["est_tech_distance_pass"] = (
            out["est_tech_distance_max_v"] <= a.max_tech_distance_v
        )
        mask &= out["est_tech_distance_pass"].to_numpy(bool)

    out["est_pre_spice_pass"] = mask

    # Simple aggregate rank score; lower is better.
    rank_cols = [
        "rank_est_gain",
        "rank_est_ugb",
        "rank_low_power",
        "rank_low_area",
        "rank_low_tech_distance",
    ]
    out["pre_spice_rank_score"] = out[rank_cols].mean(axis=1)

    a.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.output, index=False)

    print()
    print("===== FOLDED PRE-SPICE PERFORMANCE ESTIMATION =====")
    print("witnesses :", len(out))
    print("L (um)    :", a.length_um)
    print("CL (pF)   :", a.cl_pf)
    print("VDD (V)   :", a.vdd)

    summary_cols = [
        "est_gain_db",
        "est_ugb_hz",
        "est_power_w",
        "est_gate_area_um2",
        "est_tech_distance_max_v",
    ]

    print()
    print(out[summary_cols].describe(
        percentiles=[.01, .05, .10, .25, .50, .75, .90, .95, .99]
    ).T.to_string())

    passed = out[out["est_pre_spice_pass"]].copy()
    print()
    print("pre-SPICE pass rows:", len(passed))

    if a.select > 0:
        selected = (
            passed.sort_values(
                [
                    "pre_spice_rank_score",
                    "rank_est_gain",
                    "rank_est_ugb",
                    "rank_low_power",
                ]
            )
            .head(a.select)
            .copy()
        )

        selected_path = (
            a.selected_output
            if a.selected_output is not None
            else a.output.with_name(
                f"{a.output.stem}_selected_{a.select}.csv"
            )
        )

        selected_path.parent.mkdir(parents=True, exist_ok=True)
        selected.to_csv(selected_path, index=False)

        print("selected rows:", len(selected))
        print("selected output:", selected_path)

    print("all-metrics output:", a.output)


if __name__ == "__main__":
    main()

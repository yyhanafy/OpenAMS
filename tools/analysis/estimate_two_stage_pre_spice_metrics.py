#!/usr/bin/env python3
"""
Estimate cheap pre-SPICE performance metrics for every exact two-stage witness.

Metrics
-------
1. DC gain:
       A1 ~= gm1 / (gds2 + gds4)
       A2 ~= gm6 / (gds6 + gds7)
       Av ~= A1 * A2

2. Unity-gain bandwidth:
       UGB ~= gm1 / (2*pi*Cc)

3. Power:
       P ~= VDD * (I5 + I6)

4. Electrical gate-area proxy:
       Agate = L * sum(W1...W7)

gm/gds are obtained from the characterized dense technology table at the
witness DC operating point.  Technology gm and gds are normalized by the
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


# ----------------------------------------------------------------------
# CSV column compatibility
# ----------------------------------------------------------------------

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
            f"technology CSV lacks {logical}; "
            f"tried {ALIASES[logical]}"
        )
    return None


def numeric(s):
    return pd.to_numeric(s, errors="coerce")


# ----------------------------------------------------------------------
# Technology small-signal lookup
# ----------------------------------------------------------------------

class SmallSignalLookup:
    """
    Voltage-space nearest-neighbor interpolation of gm/W and gds/W.

    The OpenAMS technology characterization uses total-width scaling.
    Therefore we remove width from the lookup coordinates and interpolate
    small-signal quantities per micron of width.
    """

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
                x[mc]
                .astype(str)
                .str.lower()
                .str.contains(model_contains.lower(), regex=False)
            )
            if mask.any():
                x = x[mask].copy()

        if x.empty:
            raise RuntimeError(
                f"no technology rows for polarity={polarity}, "
                f"L={length_um}"
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

        # Collapse repeated voltage points across characterized widths.
        # Median makes the width-normalized lookup robust to small
        # characterization/model deviations.
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

    def query(
        self,
        vgs: np.ndarray,
        vds: np.ndarray,
        vbs: np.ndarray,
        width_um: np.ndarray,
    ):
        pts = np.column_stack([
            np.abs(vgs),
            np.abs(vds),
            np.abs(vbs),
        ])

        k = min(self.k, len(self.points))

        dist, idx = self.tree.query(
            pts,
            k=k,
            workers=-1,
        )

        if k == 1:
            dist = dist[:, None]
            idx = idx[:, None]

        # Exact neighbor gets overwhelming weight; otherwise IDW.
        weights = 1.0 / np.maximum(dist, 1e-9) ** 2
        weights /= weights.sum(axis=1, keepdims=True)

        gm_u = np.sum(
            weights * self.gm_per_um[idx],
            axis=1,
        )

        gds_u = np.sum(
            weights * self.gds_per_um[idx],
            axis=1,
        )

        gm = gm_u * width_um
        gds = gds_u * width_um

        nearest_distance = dist[:, 0]

        return gm, gds, nearest_distance


# ----------------------------------------------------------------------
# Two-stage operating-point reconstruction
# ----------------------------------------------------------------------

def require(df, names):
    missing = [x for x in names if x not in df.columns]
    if missing:
        raise RuntimeError(
            "witness CSV missing required fields: "
            + ", ".join(missing)
        )


def arr(df, name):
    return numeric(df[name]).to_numpy(float)


def device_operating_points(df, vdd, vin):
    n1 = arr(df, "n1_v")
    n2 = arr(df, "n2_v")
    tail = arr(df, "vtail_v")
    vbias = arr(df, "vbias_v")
    vout = arr(df, "vout_v")

    # All voltage coordinates are returned as positive magnitudes,
    # matching the OpenAMS dense technology representation.

    return {
        "M1": {
            "polarity": "nmos",
            "w": arr(df, "w_m1_um"),
            "vgs": np.abs(vin - tail),
            "vds": np.abs(n1 - tail),
            "vbs": np.abs(0.0 - tail),
        },
        "M2": {
            "polarity": "nmos",
            "w": arr(df, "w_m2_um"),
            "vgs": np.abs(vin - tail),
            "vds": np.abs(n2 - tail),
            "vbs": np.abs(0.0 - tail),
        },
        "M3": {
            "polarity": "pmos",
            "w": arr(df, "w_m3_um"),
            "vgs": np.abs(n1 - vdd),
            "vds": np.abs(n1 - vdd),
            "vbs": np.zeros(len(df)),
        },
        "M4": {
            "polarity": "pmos",
            "w": arr(df, "w_m4_um"),
            "vgs": np.abs(n1 - vdd),
            "vds": np.abs(n2 - vdd),
            "vbs": np.zeros(len(df)),
        },
        "M5": {
            "polarity": "nmos",
            "w": arr(df, "w_m5_um"),
            "vgs": np.abs(vbias),
            "vds": np.abs(tail),
            "vbs": np.zeros(len(df)),
        },
        "M6": {
            "polarity": "pmos",
            "w": arr(df, "w_m6_um"),
            "vgs": np.abs(n2 - vdd),
            "vds": np.abs(vout - vdd),
            "vbs": np.zeros(len(df)),
        },
        "M7": {
            "polarity": "nmos",
            "w": arr(df, "w_m7_um"),
            "vgs": np.abs(vbias),
            "vds": np.abs(vout),
            "vbs": np.zeros(len(df)),
        },
    }


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Estimate gain, UGB, power and electrical gate area "
            "for two-stage hierarchical witnesses."
        )
    )

    p.add_argument(
        "--witnesses",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--technology-csv",
        type=Path,
        required=True,
    )

    p.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    p.add_argument("--length-um", type=float, default=0.15)
    p.add_argument("--vdd", type=float, default=1.8)
    p.add_argument("--vin", type=float, default=0.9)
    p.add_argument("--cc-pf", type=float, default=4.0)
    p.add_argument("--neighbors", type=int, default=8)

    p.add_argument(
        "--nmos-model-contains",
        default="nfet",
    )
    p.add_argument(
        "--pmos-model-contains",
        default="pfet",
    )

    return p.parse_args()


def main():
    a = parse_args()

    if not a.witnesses.is_file():
        raise SystemExit(f"missing witnesses: {a.witnesses}")

    if not a.technology_csv.is_file():
        raise SystemExit(
            f"missing technology CSV: {a.technology_csv}"
        )

    print("loading witnesses...")
    df = pd.read_csv(a.witnesses)

    required = [
        "w_m1_um", "w_m2_um",
        "w_m3_um", "w_m4_um",
        "w_m5_um", "w_m6_um", "w_m7_um",
        "i_m5_a", "i_m6_a",
        "vtail_v", "n1_v", "n2_v",
        "vbias_v", "vout_v",
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

    ops = device_operating_points(
        df,
        vdd=a.vdd,
        vin=a.vin,
    )

    out = df.copy()

    print("querying device small-signal parameters...")

    for name, spec in ops.items():
        lookup = nmos if spec["polarity"] == "nmos" else pmos

        gm, gds, dist = lookup.query(
            spec["vgs"],
            spec["vds"],
            spec["vbs"],
            spec["w"],
        )

        tag = name.lower()

        out[f"est_{tag}_gm_s"] = gm
        out[f"est_{tag}_gds_s"] = gds
        out[f"est_{tag}_ro_ohm"] = (
            1.0 / np.maximum(gds, 1e-30)
        )
        out[f"est_{tag}_tech_distance_v"] = dist

    # --------------------------------------------------------------
    # 1. Gain
    # --------------------------------------------------------------

    gm1 = out["est_m1_gm_s"].to_numpy(float)
    gm6 = out["est_m6_gm_s"].to_numpy(float)

    gds2 = out["est_m2_gds_s"].to_numpy(float)
    gds4 = out["est_m4_gds_s"].to_numpy(float)
    gds6 = out["est_m6_gds_s"].to_numpy(float)
    gds7 = out["est_m7_gds_s"].to_numpy(float)

    stage1_gain = gm1 / np.maximum(
        gds2 + gds4,
        1e-30,
    )

    stage2_gain = gm6 / np.maximum(
        gds6 + gds7,
        1e-30,
    )

    gain_vv = stage1_gain * stage2_gain

    out["est_stage1_gain_vv"] = stage1_gain
    out["est_stage2_gain_vv"] = stage2_gain
    out["est_gain_vv"] = gain_vv
    out["est_gain_db"] = (
        20.0 * np.log10(
            np.maximum(np.abs(gain_vv), 1e-30)
        )
    )

    # --------------------------------------------------------------
    # 2. UGB
    # --------------------------------------------------------------

    cc_f = a.cc_pf * 1e-12

    out["est_ugb_hz"] = (
        gm1 / (2.0 * math.pi * cc_f)
    )

    # --------------------------------------------------------------
    # 3. Power
    # --------------------------------------------------------------

    i5 = np.abs(arr(out, "i_m5_a"))
    i6 = np.abs(arr(out, "i_m6_a"))

    out["est_power_w"] = (
        a.vdd * (i5 + i6)
    )

    # --------------------------------------------------------------
    # 4. Electrical gate-area proxy
    # --------------------------------------------------------------

    widths = np.zeros(len(out), dtype=float)

    for i in range(1, 8):
        widths += np.abs(arr(out, f"w_m{i}_um"))

    out["est_total_width_um"] = widths
    out["est_gate_area_um2"] = (
        a.length_um * widths
    )

    # --------------------------------------------------------------
    # Technology lookup quality
    # --------------------------------------------------------------

    dcols = [
        f"est_m{i}_tech_distance_v"
        for i in range(1, 8)
    ]

    out["est_tech_distance_max_v"] = (
        out[dcols].max(axis=1)
    )

    out["est_tech_distance_mean_v"] = (
        out[dcols].mean(axis=1)
    )

    # --------------------------------------------------------------
    # Ranking helpers
    # --------------------------------------------------------------

    out["rank_est_gain"] = (
        out["est_gain_db"]
        .rank(method="first", ascending=False)
        .astype(int)
    )

    out["rank_est_ugb"] = (
        out["est_ugb_hz"]
        .rank(method="first", ascending=False)
        .astype(int)
    )

    out["rank_low_power"] = (
        out["est_power_w"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    out["rank_low_area"] = (
        out["est_gate_area_um2"]
        .rank(method="first", ascending=True)
        .astype(int)
    )

    a.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.output, index=False)

    print()
    print("===== PRE-SPICE PERFORMANCE ESTIMATION =====")
    print("witnesses :", len(out))
    print("L (um)    :", a.length_um)
    print("Cc (pF)   :", a.cc_pf)
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

    print()
    print("===== TOP 20 PREDICTED GAIN =====")

    show = [
        "independent_point_index",
        "witness_rank",
        "w_m1_um",
        "w_m3_um",
        "w_m5_um",
        "w_m6_um",
        "w_m7_um",
        "i_m5_a",
        "est_stage1_gain_vv",
        "est_stage2_gain_vv",
        "est_gain_db",
        "est_ugb_hz",
        "est_power_w",
        "est_gate_area_um2",
        "est_tech_distance_max_v",
    ]

    show = [c for c in show if c in out.columns]

    print(
        out.nsmallest(20, "rank_est_gain")[show]
        .to_string(index=False)
    )

    print()
    print("output:", a.output)


if __name__ == "__main__":
    main()

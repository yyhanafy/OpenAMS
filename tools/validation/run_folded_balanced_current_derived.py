#!/usr/bin/env python3
"""
Balanced, current-derived folded-cascode component tables.

For a fixed independent seed (W1, I3):

    I1 = I2 = 0.5*I3
    I4 = I5 = 1.5*I3
    I6 = I7 = I8 = I9 = I10 = I11 = I3

Balanced cut coordinates:

    VP = psrc_left = psrc_right
    VX = x = vout

Independent component feasibility tables:

    A(W1, I3, VP)       -> M1,M2,M3 feasible?
    B(I3, VP, VX)       -> M4,M5,M6,M7 feasible?
    C(I3, VX)           -> M8,M9,M10,M11 feasible?

The full DC witness exists only where:
    A.VP == B.VP
    B.VX == C.VX

No component consumes another component's witnesses.
"""
from __future__ import annotations

import argparse
import copy
import csv
import subprocess
import sys
from pathlib import Path

import yaml


DEFAULT_PLAN = Path(
    "examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml"
)
DEFAULT_ENGINE = Path("tools/validation/witness_engine.py")
DEFAULT_WORK = Path("runtime/folded_balanced_current_derived")


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def stage(base, sid):
    for s in base["stages"]:
        if s["id"] == sid:
            return copy.deepcopy(s)
    raise KeyError(sid)


def dev(base, name):
    for d in base["final"]["devices"]:
        if d["name"] == name:
            return copy.deepcopy(d)
    raise KeyError(name)


def real(rows):
    return [
        r for r in rows
        if r.get("generation_status") == "WITNESS"
        and r.get("witness_rank") not in (None, "")
    ]


def shell(base, name, cov, out, keep, bindings, stages, final, aliases):
    return {
        "schema_version": base.get("schema_version", 1),
        "name": name,
        "coverage_csv": str(cov),
        "output_csv": str(out),
        "witnesses_per_point": keep,
        "sat_margin_v": base.get("sat_margin_v", 0.05),
        "mlp": copy.deepcopy(base["mlp"]),
        "constants": copy.deepcopy(base["constants"]),
        "point_bindings": bindings,
        "derived_bindings": {
            "i_input": "0.5 * i3_target",
            "i_upper": "1.5 * i3_target",
            "i_fold": "i3_target",
            "i_lower": "i3_target",
        },
        "stages": stages,
        "final": final,
        "csv_aliases": aliases,
    }


def run_engine(root, engine, plan, keep):
    cmd = [
        sys.executable, str(engine),
        "--plan", str(plan),
        "--root", str(root),
        "--witnesses-per-point", str(keep),
    ]
    print("\nRUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=root, check=True)


def linspace(lo, hi, n):
    if n == 1:
        return [float(lo)]
    step = (hi - lo) / (n - 1)
    return [float(lo + i * step) for i in range(n)]


def build_coverages(work, w1, i3, vp_count, vx_count):
    # Use the same broad voltage ranges as the original witness plan.
    vp_grid = linspace(0.001, 1.799, vp_count)
    vx_grid = linspace(0.05, 1.75, vx_count)

    a = []
    for i, vp in enumerate(vp_grid):
        a.append({
            "point_index": i,
            "w_m1_um": w1,
            "i_m3_a": i3,
            "vp_v": vp,
        })

    b = []
    k = 0
    for vp in vp_grid:
        for vx in vx_grid:
            b.append({
                "point_index": k,
                "i_m3_a": i3,
                "vp_v": vp,
                "vx_v": vx,
            })
            k += 1

    c = []
    for i, vx in enumerate(vx_grid):
        c.append({
            "point_index": i,
            "i_m3_a": i3,
            "vx_v": vx,
        })

    ap = work / "A_coverage.csv"
    bp = work / "B_coverage.csv"
    cp = work / "C_coverage.csv"
    write_csv(ap, a)
    write_csv(bp, b)
    write_csv(cp, c)
    return ap, bp, cp, vp_grid, vx_grid


def build_A(base, cov, out, keep):
    s1 = stage(base, "input_pair")

    # VP is now an independent interface coordinate.
    s1["sweeps"].pop("psrc", None)
    s1["derived"] = {
        "psrc_left": "vp",
        "psrc_right": "vp",
    }
    s1["outputs"] = {"tail": "tail"}
    s1["selection_coordinates"] = ["tail"]
    s1["diversity_keys"] = ["tail"]
    s1["global_cap"] = 64

    s2 = stage(base, "tail_source")
    s2["global_cap"] = 64

    bindings = {
        "w1": {"column": "w_m1_um"},
        "i3_target": {"column": "i_m3_a"},
        "vp": {"column": "vp_v"},
    }

    final = {
        "devices": [dev(base, n) for n in ("M1", "M2", "M3")],
        "residuals": {
            "tail_kcl": base["final"]["residuals"]["tail_kcl"],
            "m3_target": base["final"]["residuals"]["m3_target"],
        },
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n]
            for n in ("M1", "M2", "M3")
        },
        "constraints": [
            "M1_domain & M2_domain & M3_domain",
            "((psrc_left-tail)-M1_vdsat)>=sat_margin_v",
            "((psrc_right-tail)-M2_vdsat)>=sat_margin_v",
            "((tail-vss)-M3_vdsat)>=sat_margin_v",
        ],
    }

    plan = shell(
        base, "folded_A_balanced_current_derived",
        cov, out, keep, bindings, [s1, s2], final,
        {
            "w_m1_um": "w1",
            "i_m3_a": "i3_target",
            "vp_v": "vp",
            "tail_v": "tail",
            "vnb1_v": "vnb1",
            "w_m3_um": "w3",
        },
    )
    plan["derived_bindings"].update({
        "psrc_left": "vp",
        "psrc_right": "vp",
    })
    return plan


def build_B(base, cov, out, keep):
    upper = stage(base, "upper_sources")

    # The cut voltage VP is fixed; do not let this stage derive/sweep psrc.
    # The original stage only needs VP to solve M4/M5 bias/width.
    upper["global_cap"] = 64

    folded = {
        "id": "folded_pair_balanced_fixed_current",
        "sweeps": {
            "vpb2": {
                "source": "row_interval",
                "prefix": "vpb2_node",
                "unit": "v",
                "default_lo": 0.1,
                "default_hi": 1.7,
                "count": 81,
                "spacing": "linear",
            },
            "w6": {
                "source": "model_width_interval",
                "polarity": "pmos",
                "row_interval": {
                    "prefix": "w_m6",
                    "unit": "um",
                    "default_lo": 0.42,
                    "default_hi": 100.0,
                },
                "count": 80,
                "spacing": "geom",
            },
        },
        "derived": {
            "psrc_left": "vp",
            "psrc_right": "vp",
            "x": "vx",
            "vout": "vx",
        },
        "devices": [
            {
                "name": "M6",
                "polarity": "pmos",
                "width": "w6",
                "vgs": "psrc_left-vpb2",
                "vds": "psrc_left-x",
                "vbs": "vdd-psrc_left",
            },
            {
                "name": "M7",
                "polarity": "pmos",
                "width": "w6",
                "vgs": "psrc_right-vpb2",
                "vds": "psrc_right-vout",
                "vbs": "vdd-psrc_right",
            },
        ],
        "constraints": [
            "M6_domain & M7_domain",
            "(psrc_left-x)>=M6_vdsat+sat_margin_v",
            "(psrc_right-vout)>=M7_vdsat+sat_margin_v",
            "relerr(M6_id,i_fold)<=current_rel_tol",
            "relerr(M7_id,i_fold)<=current_rel_tol",
        ],
        "score": "max(relerr(M6_id,i_fold),relerr(M7_id,i_fold))",
        "outputs": {"vpb2": "vpb2", "w6": "w6"},
        "selection_coordinates": ["vpb2", "w6"],
        "per_parent_keep": 3,
        "global_cap": 64,
        "diversity_keys": ["vpb2", "w6"],
    }

    # Force the upper stage to use the same VP interface coordinate.
    upper.setdefault("derived", {})
    upper["derived"]["psrc_left"] = "vp"
    upper["derived"]["psrc_right"] = "vp"

    bindings = {
        "i3_target": {"column": "i_m3_a"},
        "vp": {"column": "vp_v"},
        "vx": {"column": "vx_v"},
    }

    final = {
        "devices": [dev(base, n) for n in ("M4", "M5", "M6", "M7")],
        "residuals": {},
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n]
            for n in ("M4", "M5", "M6", "M7")
        },
        "constraints": [
            "M4_domain & M5_domain & M6_domain & M7_domain",
            "((vdd-psrc_left)-M4_vdsat)>=sat_margin_v",
            "((vdd-psrc_right)-M5_vdsat)>=sat_margin_v",
            "((psrc_left-x)-M6_vdsat)>=sat_margin_v",
            "((psrc_right-vout)-M7_vdsat)>=sat_margin_v",
        ],
    }

    plan = shell(
        base, "folded_B_balanced_current_derived",
        cov, out, keep, bindings, [upper, folded], final,
        {
            "i_m3_a": "i3_target",
            "vp_v": "vp",
            "vx_v": "vx",
            "vpb1_v": "vpb1",
            "w_m4_um": "w4",
            "vpb2_v": "vpb2",
            "w_m6_um": "w6",
        },
    )
    plan["derived_bindings"].update({
        "psrc_left": "vp",
        "psrc_right": "vp",
        "x": "vx",
        "vout": "vx",
    })
    return plan


def build_C(base, cov, out, keep):
    lower = {
        "id": "lower_sink_balanced_fixed_current",
        "sweeps": {
            "nsink": {
                "source": "row_interval",
                "prefix": "nsink_left",
                "unit": "v",
                "default_lo": 0.01,
                "default_hi": 1.6,
                "count": 31,
                "spacing": "linear",
            },
            "w8": {
                "source": "model_width_interval",
                "polarity": "nmos",
                "row_interval": {
                    "prefix": "w_m8",
                    "unit": "um",
                    "default_lo": 0.42,
                    "default_hi": 100.0,
                },
                "count": 80,
                "spacing": "geom",
            },
        },
        "derived": {
            "x": "vx",
            "vout": "vx",
            "nsink_left": "nsink",
            "nsink_right": "nsink",
        },
        "devices": [
            {
                "name": "M10",
                "polarity": "nmos",
                "width": "w8",
                "vgs": "x-vss",
                "vds": "nsink_left-vss",
                "vbs": "0.0",
            },
            {
                "name": "M11",
                "polarity": "nmos",
                "width": "w8",
                "vgs": "x-vss",
                "vds": "nsink_right-vss",
                "vbs": "0.0",
            },
        ],
        "constraints": [
            "M10_domain & M11_domain",
            "(nsink_left-vss)>=M10_vdsat+sat_margin_v",
            "(nsink_right-vss)>=M11_vdsat+sat_margin_v",
            "relerr(M10_id,i_lower)<=current_rel_tol",
            "relerr(M11_id,i_lower)<=current_rel_tol",
        ],
        "score": "max(relerr(M10_id,i_lower),relerr(M11_id,i_lower))",
        "outputs": {
            "nsink_left": "nsink_left",
            "nsink_right": "nsink_right",
            "w8": "w8",
        },
        "selection_coordinates": ["nsink", "w8"],
        "per_parent_keep": 3,
        "global_cap": 64,
        "diversity_keys": ["nsink_left", "w8"],
    }

    cascode = {
        "id": "lower_cascode_balanced_fixed_current",
        "sweeps": {
            "vnb2": {
                "source": "row_interval",
                "prefix": "vnb2_node",
                "unit": "v",
                "default_lo": 0.1,
                "default_hi": 1.7,
                "count": 81,
                "spacing": "linear",
            },
        },
        "derived": {
            "x": "vx",
            "vout": "vx",
        },
        "devices": [
            {
                "name": "M8",
                "polarity": "nmos",
                "width": "w8",
                "vgs": "vnb2-nsink_left",
                "vds": "x-nsink_left",
                "vbs": "nsink_left-vss",
            },
            {
                "name": "M9",
                "polarity": "nmos",
                "width": "w8",
                "vgs": "vnb2-nsink_right",
                "vds": "vout-nsink_right",
                "vbs": "nsink_right-vss",
            },
        ],
        "constraints": [
            "M8_domain & M9_domain",
            "(x-nsink_left)>=M8_vdsat+sat_margin_v",
            "(vout-nsink_right)>=M9_vdsat+sat_margin_v",
            "relerr(M8_id,i_lower)<=current_rel_tol",
            "relerr(M9_id,i_lower)<=current_rel_tol",
        ],
        "score": "max(relerr(M8_id,i_lower),relerr(M9_id,i_lower))",
        "outputs": {"vnb2": "vnb2"},
        "selection_coordinates": ["vnb2"],
        "per_parent_keep": 3,
        "global_cap": 64,
        "diversity_keys": ["nsink_left", "w8", "vnb2"],
    }

    bindings = {
        "i3_target": {"column": "i_m3_a"},
        "vx": {"column": "vx_v"},
    }

    final = {
        "devices": [dev(base, n) for n in ("M8", "M9", "M10", "M11")],
        "residuals": {
            "nsink_left_kcl": base["final"]["residuals"]["nsink_left_kcl"],
            "nsink_right_kcl": base["final"]["residuals"]["nsink_right_kcl"],
        },
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n]
            for n in ("M8", "M9", "M10", "M11")
        },
        "constraints": [
            "M8_domain & M9_domain & M10_domain & M11_domain",
            "((x-nsink_left)-M8_vdsat)>=sat_margin_v",
            "((vout-nsink_right)-M9_vdsat)>=sat_margin_v",
            "((nsink_left-vss)-M10_vdsat)>=sat_margin_v",
            "((nsink_right-vss)-M11_vdsat)>=sat_margin_v",
        ],
    }

    plan = shell(
        base, "folded_C_balanced_current_derived",
        cov, out, keep, bindings, [lower, cascode], final,
        {
            "i_m3_a": "i3_target",
            "vx_v": "vx",
            "nsink_left_v": "nsink_left",
            "nsink_right_v": "nsink_right",
            "w_m8_um": "w8",
            "vnb2_v": "vnb2",
        },
    )
    plan["derived_bindings"].update({
        "x": "vx",
        "vout": "vx",
    })
    return plan


def q(v):
    return round(float(v), 9)


def join_tables(a_rows, b_rows, c_rows):
    ar = real(a_rows)
    br = real(b_rows)
    cr = real(c_rows)

    A = {}
    for r in ar:
        A.setdefault(q(r["vp_v"]), []).append(r)

    C = {}
    for r in cr:
        C.setdefault(q(r["vx_v"]), []).append(r)

    joined = []
    for b in br:
        vp = q(b["vp_v"])
        vx = q(b["vx_v"])
        if vp not in A or vx not in C:
            continue
        for a in A[vp]:
            for c in C[vx]:
                joined.append({
                    "vp_v": b["vp_v"],
                    "vx_v": b["vx_v"],
                    "a_rank": a["witness_rank"],
                    "b_rank": b["witness_rank"],
                    "c_rank": c["witness_rank"],
                    "w_m1_um": a.get("w_m1_um", ""),
                    "i_m3_a": b.get("i_m3_a", ""),
                    "tail_v": a.get("tail_v", ""),
                    "vnb1_v": a.get("vnb1_v", ""),
                    "w_m3_um": a.get("w_m3_um", ""),
                    "vpb1_v": b.get("vpb1_v", ""),
                    "w_m4_um": b.get("w_m4_um", ""),
                    "vpb2_v": b.get("vpb2_v", ""),
                    "w_m6_um": b.get("w_m6_um", ""),
                    "nsink_left_v": c.get("nsink_left_v", ""),
                    "nsink_right_v": c.get("nsink_right_v", ""),
                    "w_m8_um": c.get("w_m8_um", ""),
                    "vnb2_v": c.get("vnb2_v", ""),
                })
    return joined


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--base-plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--w1", type=float, default=1.0)
    ap.add_argument("--i3-ua", type=float, default=10.0)
    ap.add_argument("--vp-count", type=int, default=31)
    ap.add_argument("--vx-count", type=int, default=21)
    ap.add_argument("--a-witnesses", type=int, default=5)
    ap.add_argument("--b-witnesses", type=int, default=5)
    ap.add_argument("--c-witnesses", type=int, default=5)
    args = ap.parse_args()

    root = args.root.resolve()
    absr = lambda p: p if p.is_absolute() else (root / p).resolve()
    base = load_yaml(absr(args.base_plan))
    engine = absr(args.engine)
    work = absr(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    i3 = args.i3_ua * 1e-6
    acov, bcov, ccov, vpgrid, vxgrid = build_coverages(
        work, args.w1, i3, args.vp_count, args.vx_count
    )

    aplan, aout = work/"A_plan.yaml", work/"A_table.csv"
    bplan, bout = work/"B_plan.yaml", work/"B_table.csv"
    cplan, cout = work/"C_plan.yaml", work/"C_table.csv"
    jout = work/"ABC_joined.csv"

    save_yaml(aplan, build_A(base, acov, aout, args.a_witnesses))
    save_yaml(bplan, build_B(base, bcov, bout, args.b_witnesses))
    save_yaml(cplan, build_C(base, ccov, cout, args.c_witnesses))

    print("\n===== A: M1-M3, independent VP =====")
    run_engine(root, engine, aplan, args.a_witnesses)

    print("\n===== B: M4-M7, independent VP,VX =====")
    run_engine(root, engine, bplan, args.b_witnesses)

    print("\n===== C: M8-M11, independent VX =====")
    run_engine(root, engine, cplan, args.c_witnesses)

    ar, br, cr = read_csv(aout), read_csv(bout), read_csv(cout)
    joined = join_tables(ar, br, cr)
    write_csv(jout, joined)

    avp = {q(r["vp_v"]) for r in real(ar)}
    bvpvx = {(q(r["vp_v"]), q(r["vx_v"])) for r in real(br)}
    cvx = {q(r["vx_v"]) for r in real(cr)}
    viable_b = {(vp, vx) for vp, vx in bvpvx if vp in avp and vx in cvx}

    print("\n===== BALANCED CURRENT-DERIVED FOLDED JOIN =====")
    print(f"W1                            : {args.w1:.6g} um")
    print(f"I3                            : {args.i3_ua:.6g} uA")
    print("Derived currents:")
    print(f"  I1=I2                       : {0.5*args.i3_ua:.6g} uA")
    print(f"  I4=I5                       : {1.5*args.i3_ua:.6g} uA")
    print(f"  I6..I11                     : {args.i3_ua:.6g} uA")
    print(f"VP grid cells                 : {len(vpgrid)}")
    print(f"VX grid cells                 : {len(vxgrid)}")
    print(f"A coverage cells              : {len(read_csv(acov))}")
    print(f"B coverage cells              : {len(read_csv(bcov))}")
    print(f"C coverage cells              : {len(read_csv(ccov))}")
    print(f"A feasible VP cells           : {len(avp)}")
    print(f"B feasible (VP,VX) cells      : {len(bvpvx)}")
    print(f"C feasible VX cells           : {len(cvx)}")
    print(f"Full interface cells A∩B∩C    : {len(viable_b)}")
    print(f"Joined full witnesses          : {len(joined)}")
    print(f"\nA table: {aout}")
    print(f"B table: {bout}")
    print(f"C table: {cout}")
    print(f"JOINED : {jout}")

    if not joined:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

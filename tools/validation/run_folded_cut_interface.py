#!/usr/bin/env python3
"""
Folded-cascode hierarchical feasibility experiment with cut-node voltages
treated as explicit independent interface variables.

Physical components:
    A = M1, M2, M3
    B = M4, M5, M6, M7
    C = M8, M9, M10, M11

Interfaces:
    A <-> B : VD1 = psrc_left, VD2 = psrc_right
    B <-> C : VD6 = x,          VD7 = vout

The existing transistor MLP remains the oracle.  No component MLP is used.
"""
from __future__ import annotations

import argparse
import copy
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
import yaml


DEFAULT_PLAN = Path("examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml")
DEFAULT_ENGINE = Path("tools/validation/witness_engine.py")
DEFAULT_WORK = Path("runtime/folded_cascode_cut_interface")


def ry(p):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def wy(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(d, f, sort_keys=False)


def rcsv(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def wcsv(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        p.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def pick(r, *names):
    for n in names:
        if r.get(n) not in (None, ""):
            return r[n]
    raise KeyError(f"none of {names} found/nonempty; columns={sorted(r)}")


def real_rows(rows):
    return [
        r for r in rows
        if r.get("witness_rank") not in (None, "")
        and r.get("generation_status") == "WITNESS"
    ]


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


def shell(base, name, coverage, output, keep, bindings, stages, final, aliases):
    return {
        "schema_version": base.get("schema_version", 1),
        "name": name,
        "coverage_csv": str(coverage),
        "output_csv": str(output),
        "witnesses_per_point": keep,
        "sat_margin_v": base.get("sat_margin_v", 0.05),
        "mlp": copy.deepcopy(base["mlp"]),
        "constants": copy.deepcopy(base["constants"]),
        "point_bindings": bindings,
        "derived_bindings": copy.deepcopy(base.get("derived_bindings", {})),
        "stages": stages,
        "final": final,
        "csv_aliases": aliases,
    }


def make_coverage(path):
    # Five points only for the first smoke test: one I3, W1 sweep.
    rows = []
    for i, w1 in enumerate([1.0, 25.75, 50.5, 75.25, 100.0]):
        rows.append({"point_index": i, "w_m1_um": w1, "i_m3_a": 10e-6})
    wcsv(path, rows)


def build_a(base, cov, out, keep):
    ip = stage(base, "input_pair")

    # Critical change: the A/B cut voltages are independent coordinates.
    ip["sweeps"] = {
        "tail": {
            "source": "row_interval", "prefix": "tail", "unit": "v",
            "default_lo": 0.001, "default_hi": 0.899, "count": 41, "spacing": "linear",
        },
        "psrc_left": {
            "source": "row_interval", "prefix": "psrc_left", "unit": "v",
            "default_lo": 0.10, "default_hi": 1.70, "count": 21, "spacing": "linear",
        },
        "psrc_right": {
            "source": "row_interval", "prefix": "psrc_right", "unit": "v",
            "default_lo": 0.10, "default_hi": 1.70, "count": 21, "spacing": "linear",
        },
    }
    ip.pop("derived", None)
    ip["outputs"] = {
        "tail": "tail",
        "psrc_left": "psrc_left",
        "psrc_right": "psrc_right",
    }
    ip["selection_coordinates"] = ["tail", "psrc_left", "psrc_right"]
    ip["per_parent_keep"] = 3
    ip["global_cap"] = 128
    ip["diversity_keys"] = ["tail", "psrc_left", "psrc_right"]

    ts = stage(base, "tail_source")
    ts["global_cap"] = 128

    final = {
        "devices": [dev(base, n) for n in ("M1", "M2", "M3")],
        "residuals": {
            "tail_kcl": base["final"]["residuals"]["tail_kcl"],
            "m3_target": base["final"]["residuals"]["m3_target"],
        },
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n] for n in ("M1", "M2", "M3")
        },
        "constraints": [
            "M1_domain & M2_domain & M3_domain",
            "((psrc_left-tail)-M1_vdsat)>=sat_margin_v",
            "((psrc_right-tail)-M2_vdsat)>=sat_margin_v",
            "((tail-vss)-M3_vdsat)>=sat_margin_v",
        ],
    }
    return shell(
        base, "folded_A_cut_independent", cov, out, keep,
        copy.deepcopy(base["point_bindings"]),
        [ip, ts], final,
        {
            "w_m1_um": "w1", "i_m3_a": "i3_target",
            "tail_v": "tail", "v_d_m1_v": "psrc_left",
            "v_d_m2_v": "psrc_right", "psrc_left_v": "psrc_left",
            "psrc_right_v": "psrc_right", "vnb1_v": "vnb1",
            "w_m3_um": "w3",
        },
    )


def make_b_cov(a_rows):
    out = []
    for i, a in enumerate(real_rows(a_rows)):
        out.append({
            "point_index": i,
            "parent_point_index": pick(a, "point_index"),
            "parent_a_rank": pick(a, "witness_rank"),
            "w_m1_um": pick(a, "w_m1_um"),
            "i_m3_a": pick(a, "i_m3_a"),
            "tail_v": pick(a, "tail_v"),
            "psrc_left_v": pick(a, "psrc_left_v", "v_d_m1_v"),
            "psrc_right_v": pick(a, "psrc_right_v", "v_d_m2_v"),
            "vnb1_v": pick(a, "vnb1_v"),
            "w_m3_um": pick(a, "w_m3_um"),
        })
    return out


def build_b(base, cov, out, keep):
    upper = stage(base, "upper_sources")
    upper["global_cap"] = 64

    # Custom B output-side stage:
    # VD6=x and VD7=vout are independent cut coordinates.
    folded = {
        "id": "folded_pair_with_independent_cut",
        "sweeps": {
            "x": {
                "source": "row_interval", "prefix": "x", "unit": "v",
                "default_lo": 0.10, "default_hi": 1.55, "count": 13, "spacing": "linear",
            },
            "vout": {
                "source": "row_interval", "prefix": "vout", "unit": "v",
                "default_lo": 0.25, "default_hi": 1.55, "count": 13, "spacing": "linear",
            },
            "vpb2": {
                "source": "row_interval", "prefix": "vpb2_node", "unit": "v",
                "default_lo": 0.1, "default_hi": 1.7, "count": 41, "spacing": "linear",
            },
            "w6": {
                "source": "model_width_interval", "polarity": "pmos",
                "row_interval": {
                    "prefix": "w_m6", "unit": "um",
                    "default_lo": 0.42, "default_hi": 100.0,
                },
                "count": 60, "spacing": "geom",
            },
        },
        "devices": [
            {
                "name": "M6", "polarity": "pmos", "width": "w6",
                "vgs": "psrc_left-vpb2", "vds": "psrc_left-x",
                "vbs": "vdd-psrc_left",
            },
            {
                "name": "M7", "polarity": "pmos", "width": "w6",
                "vgs": "psrc_right-vpb2", "vds": "psrc_right-vout",
                "vbs": "vdd-psrc_right",
            },
        ],
        "constraints": [
            "M6_domain & M7_domain",
            "(psrc_left-x)>=M6_vdsat+sat_margin_v",
            "(psrc_right-vout)>=M7_vdsat+sat_margin_v",
            "relerr(M6_id,i3_target)<=current_rel_tol",
            "relerr(M7_id,i3_target)<=current_rel_tol",
        ],
        "score": "max(relerr(M6_id,i3_target),relerr(M7_id,i3_target))",
        "outputs": {"x": "x", "vout": "vout", "vpb2": "vpb2", "w6": "w6"},
        "selection_coordinates": ["x", "vout", "vpb2", "w6"],
        "per_parent_keep": 3,
        "global_cap": 128,
        "diversity_keys": ["psrc_left", "psrc_right", "x", "vout", "vpb2", "w6"],
    }

    bindings = {
        "w1": {"column": "w_m1_um"},
        "i3_target": {"column": "i_m3_a"},
        "tail": {"column": "tail_v"},
        "psrc_left": {"column": "psrc_left_v"},
        "psrc_right": {"column": "psrc_right_v"},
        "vnb1": {"column": "vnb1_v"},
        "w3": {"column": "w_m3_um"},
        "parent_point_index": {"column": "parent_point_index"},
        "parent_a_rank": {"column": "parent_a_rank"},
    }

    final = {
        "devices": [dev(base, n) for n in ("M4", "M5", "M6", "M7")],
        # No cross-component residuals here.  Currents are checked locally
        # against their target values in the stages.
        "residuals": {},
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n] for n in ("M4", "M5", "M6", "M7")
        },
        "constraints": [
            "M4_domain & M5_domain & M6_domain & M7_domain",
            "((vdd-psrc_left)-M4_vdsat)>=sat_margin_v",
            "((vdd-psrc_right)-M5_vdsat)>=sat_margin_v",
            "((psrc_left-x)-M6_vdsat)>=sat_margin_v",
            "((psrc_right-vout)-M7_vdsat)>=sat_margin_v",
        ],
    }

    return shell(
        base, "folded_B_cut_independent", cov, out, keep, bindings,
        [upper, folded], final,
        {
            "parent_point_index": "parent_point_index",
            "parent_a_rank": "parent_a_rank",
            "w_m1_um": "w1", "i_m3_a": "i3_target",
            "psrc_left_v": "psrc_left", "psrc_right_v": "psrc_right",
            "vpb1_v": "vpb1", "w_m4_um": "w4",
            "v_d_m6_v": "x", "x_v": "x",
            "v_d_m7_v": "vout", "vout_v": "vout",
            "vpb2_v": "vpb2", "w_m6_um": "w6",
        },
    )


def make_c_cov(b_rows):
    out = []
    for i, b in enumerate(real_rows(b_rows)):
        out.append({
            "point_index": i,
            "parent_point_index": pick(b, "parent_point_index"),
            "parent_a_rank": pick(b, "parent_a_rank"),
            "parent_b_rank": pick(b, "witness_rank"),
            "w_m1_um": pick(b, "w_m1_um"),
            "i_m3_a": pick(b, "i_m3_a"),
            "psrc_left_v": pick(b, "psrc_left_v"),
            "psrc_right_v": pick(b, "psrc_right_v"),
            "vpb1_v": pick(b, "vpb1_v"),
            "w_m4_um": pick(b, "w_m4_um"),
            "x_v": pick(b, "x_v", "v_d_m6_v"),
            "vout_v": pick(b, "vout_v", "v_d_m7_v"),
            "vpb2_v": pick(b, "vpb2_v"),
            "w_m6_um": pick(b, "w_m6_um"),
        })
    return out


def build_c(base, cov, out, keep):
    # C receives VD8=x and VD9=vout as fixed interface variables.
    sink = {
        "id": "lower_sink_with_fixed_cut",
        "sweeps": {
            "nsink_left": {
                "source": "row_interval", "prefix": "nsink_left", "unit": "v",
                "default_lo": 0.02, "default_hi": 1.25, "count": 21, "spacing": "linear",
            },
            "nsink_right": {
                "source": "row_interval", "prefix": "nsink_right", "unit": "v",
                "default_lo": 0.02, "default_hi": 1.25, "count": 21, "spacing": "linear",
            },
            "w8": {
                "source": "model_width_interval", "polarity": "nmos",
                "row_interval": {
                    "prefix": "w_m8", "unit": "um",
                    "default_lo": 0.42, "default_hi": 100.0,
                },
                "count": 60, "spacing": "geom",
            },
        },
        "devices": [
            {
                "name": "M10", "polarity": "nmos", "width": "w8",
                "vgs": "x-vss", "vds": "nsink_left-vss", "vbs": "0.0",
            },
            {
                "name": "M11", "polarity": "nmos", "width": "w8",
                "vgs": "x-vss", "vds": "nsink_right-vss", "vbs": "0.0",
            },
        ],
        "constraints": [
            "M10_domain & M11_domain",
            "(nsink_left-vss)>=M10_vdsat+sat_margin_v",
            "(nsink_right-vss)>=M11_vdsat+sat_margin_v",
            "relerr(M10_id,i3_target)<=current_rel_tol",
            "relerr(M11_id,i3_target)<=current_rel_tol",
        ],
        "score": "max(relerr(M10_id,i3_target),relerr(M11_id,i3_target))",
        "outputs": {
            "nsink_left": "nsink_left", "nsink_right": "nsink_right", "w8": "w8"
        },
        "selection_coordinates": ["nsink_left", "nsink_right", "w8"],
        "per_parent_keep": 3,
        "global_cap": 128,
        "diversity_keys": ["x", "vout", "nsink_left", "nsink_right", "w8"],
    }

    cas = {
        "id": "lower_cascode_pair_fixed_cut",
        "sweeps": {
            "vnb2": {
                "source": "row_interval", "prefix": "vnb2_node", "unit": "v",
                "default_lo": 0.1, "default_hi": 1.7, "count": 41, "spacing": "linear",
            },
        },
        "devices": [
            {
                "name": "M8", "polarity": "nmos", "width": "w8",
                "vgs": "vnb2-nsink_left", "vds": "x-nsink_left",
                "vbs": "nsink_left-vss",
            },
            {
                "name": "M9", "polarity": "nmos", "width": "w8",
                "vgs": "vnb2-nsink_right", "vds": "vout-nsink_right",
                "vbs": "nsink_right-vss",
            },
        ],
        "constraints": [
            "M8_domain & M9_domain",
            "(x-nsink_left)>=M8_vdsat+sat_margin_v",
            "(vout-nsink_right)>=M9_vdsat+sat_margin_v",
            "relerr(M8_id,i3_target)<=current_rel_tol",
            "relerr(M9_id,i3_target)<=current_rel_tol",
        ],
        "score": "max(relerr(M8_id,i3_target),relerr(M9_id,i3_target))",
        "outputs": {"vnb2": "vnb2"},
        "selection_coordinates": ["vnb2"],
        "per_parent_keep": 3,
        "global_cap": 128,
        "diversity_keys": ["x", "vout", "nsink_left", "nsink_right", "w8", "vnb2"],
    }

    bindings = {
        "i3_target": {"column": "i_m3_a"},
        "x": {"column": "x_v"},
        "vout": {"column": "vout_v"},
        "parent_point_index": {"column": "parent_point_index"},
        "parent_a_rank": {"column": "parent_a_rank"},
        "parent_b_rank": {"column": "parent_b_rank"},
    }

    final = {
        "devices": [dev(base, n) for n in ("M8", "M9", "M10", "M11")],
        "residuals": {
            "nsink_left_kcl": base["final"]["residuals"]["nsink_left_kcl"],
            "nsink_right_kcl": base["final"]["residuals"]["nsink_right_kcl"],
        },
        "saturation_headroom": {
            n: base["final"]["saturation_headroom"][n] for n in ("M8", "M9", "M10", "M11")
        },
        "constraints": [
            "M8_domain & M9_domain & M10_domain & M11_domain",
            "((x-nsink_left)-M8_vdsat)>=sat_margin_v",
            "((vout-nsink_right)-M9_vdsat)>=sat_margin_v",
            "((nsink_left-vss)-M10_vdsat)>=sat_margin_v",
            "((nsink_right-vss)-M11_vdsat)>=sat_margin_v",
        ],
    }

    return shell(
        base, "folded_C_cut_independent", cov, out, keep, bindings,
        [sink, cas], final,
        {
            "parent_point_index": "parent_point_index",
            "parent_a_rank": "parent_a_rank",
            "parent_b_rank": "parent_b_rank",
            "i_m3_a": "i3_target",
            "v_d_m8_v": "x", "x_v": "x",
            "v_d_m9_v": "vout", "vout_v": "vout",
            "nsink_left_v": "nsink_left", "nsink_right_v": "nsink_right",
            "w_m8_um": "w8", "vnb2_v": "vnb2",
        },
    )


def run(root, engine, plan, keep, max_points=None):
    cmd = [
        sys.executable, str(engine),
        "--plan", str(plan),
        "--root", str(root),
        "--witnesses-per-point", str(keep),
    ]
    if max_points is not None:
        cmd += ["--max-points", str(max_points)]
    print("\nRUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=root, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--base-plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--max-points", type=int, default=5)
    ap.add_argument("--a-witnesses", type=int, default=16)
    ap.add_argument("--b-witnesses", type=int, default=16)
    ap.add_argument("--c-witnesses", type=int, default=8)
    args = ap.parse_args()

    root = args.root.resolve()
    absr = lambda p: p if p.is_absolute() else (root / p).resolve()
    base = ry(absr(args.base_plan))
    engine = absr(args.engine)
    work = absr(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    cov = work / "coverage.csv"
    make_coverage(cov)

    apath, aout = work/"A_plan.yaml", work/"A_witnesses.csv"
    bcp, bpath, bout = work/"B_coverage.csv", work/"B_plan.yaml", work/"B_witnesses.csv"
    ccp, cpath, cout = work/"C_coverage.csv", work/"C_plan.yaml", work/"C_witnesses.csv"

    wy(apath, build_a(base, cov, aout, args.a_witnesses))
    run(root, engine, apath, args.a_witnesses, args.max_points)
    ar = rcsv(aout)
    areal = real_rows(ar)
    print(f"\nA real interface states: {len(areal)}")
    if not areal:
        return 2

    bcov = make_b_cov(ar)
    wcsv(bcp, bcov)
    wy(bpath, build_b(base, bcp, bout, args.b_witnesses))
    run(root, engine, bpath, args.b_witnesses)
    br = rcsv(bout)
    breal = real_rows(br)
    print(f"\nB real interface states: {len(breal)}")
    if not breal:
        return 3

    ccov = make_c_cov(br)
    wcsv(ccp, ccov)
    wy(cpath, build_c(base, ccp, cout, args.c_witnesses))
    run(root, engine, cpath, args.c_witnesses)
    cr = rcsv(cout)
    creal = real_rows(cr)

    apts = {int(float(r["point_index"])) for r in areal}
    bpts = {int(float(r["parent_point_index"])) for r in breal}
    cpts = {int(float(r["parent_point_index"])) for r in creal}

    print("\n===== FOLDED CUT-INTERFACE HIERARCHICAL SEARCH =====")
    print(f"A states  (VD1,VD2 feasible) : {len(areal)}")
    print(f"B inputs                      : {len(bcov)}")
    print(f"B states  (VD6,VD7 feasible) : {len(breal)}")
    print(f"C inputs                      : {len(ccov)}")
    print(f"C witnesses                   : {len(creal)}")
    print(f"A-covered original points     : {len(apts)}")
    print(f"A+B-covered original points   : {len(bpts)}")
    print(f"A+B+C-covered original points : {len(cpts)}")
    if apts:
        print(f"A->B point survival           : {100*len(bpts)/len(apts):.2f}%")
    if bpts:
        print(f"B->C point survival           : {100*len(cpts)/len(bpts):.2f}%")
    print(f"\nA: {aout}\nB: {bout}\nC: {cout}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

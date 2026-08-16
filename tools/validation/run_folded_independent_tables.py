#!/usr/bin/env python3
"""
Independent folded-cascode component feasibility tables + exact interface join.

This is intentionally a small proof experiment.

Physical components
-------------------
A = M1,M2,M3
B = M4,M5,M6,M7
C = M8,M9,M10,M11

Shared cut-node coordinates
---------------------------
A <-> B:
    vd1 = psrc_left   (drain M1 / drain M4-source-side folded node)
    vd2 = psrc_right  (drain M2 / corresponding right node)

B <-> C:
    vd6 = x           (drain M6 / drain M8)
    vd7 = vout        (drain M7 / drain M9)

Key rule:
    A, B, and C are generated INDEPENDENTLY.
    No component consumes another component's witnesses.
    The complete circuit is formed only by an exact database-style join on
    (vd1,vd2) and (vd6,vd7).

The existing transistor MLP remains the oracle.
"""
from __future__ import annotations

import argparse
import copy
import csv
import itertools
import subprocess
import sys
from pathlib import Path

import yaml


DEFAULT_PLAN = Path(
    "examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml"
)
DEFAULT_ENGINE = Path("tools/validation/witness_engine.py")
DEFAULT_WORK = Path("runtime/folded_independent_component_tables")


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def stage(base: dict, sid: str) -> dict:
    for s in base["stages"]:
        if s["id"] == sid:
            return copy.deepcopy(s)
    raise KeyError(sid)


def device(base: dict, name: str) -> dict:
    for d in base["final"]["devices"]:
        if d["name"] == name:
            return copy.deepcopy(d)
    raise KeyError(name)


def real_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in rows
        if r.get("generation_status") == "WITNESS"
        and r.get("witness_rank") not in (None, "")
    ]


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


def run_engine(root, engine, plan, keep):
    cmd = [
        sys.executable, str(engine),
        "--plan", str(plan),
        "--root", str(root),
        "--witnesses-per-point", str(keep),
    ]
    print("\nRUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=root, check=True)


def grid3(lo, hi):
    mid = 0.5 * (lo + hi)
    return [float(lo), float(mid), float(hi)]


def build_coverages(work: Path, w1: float, i3: float):
    # Deliberately broad first grid.  The same exact values are reused by
    # neighboring component tables, which makes the final join exact.
    pab = grid3(0.55, 1.35)     # vd1, vd2 = psrc_left/right
    pbc = grid3(0.45, 1.25)     # vd6=x, vd7=vout

    a_rows = []
    k = 0
    for vd1, vd2 in itertools.product(pab, pab):
        a_rows.append({
            "point_index": k,
            "w_m1_um": w1,
            "i_m3_a": i3,
            "vd1_v": vd1,
            "vd2_v": vd2,
        })
        k += 1

    b_rows = []
    k = 0
    for vd1, vd2, vd6, vd7 in itertools.product(pab, pab, pbc, pbc):
        b_rows.append({
            "point_index": k,
            "i_m3_a": i3,
            "vd1_v": vd1,
            "vd2_v": vd2,
            "vd6_v": vd6,
            "vd7_v": vd7,
        })
        k += 1

    c_rows = []
    k = 0
    for vd6, vd7 in itertools.product(pbc, pbc):
        c_rows.append({
            "point_index": k,
            "i_m3_a": i3,
            "vd6_v": vd6,
            "vd7_v": vd7,
        })
        k += 1

    ap = work / "A_coverage.csv"
    bp = work / "B_coverage.csv"
    cp = work / "C_coverage.csv"
    write_csv(ap, a_rows)
    write_csv(bp, b_rows)
    write_csv(cp, c_rows)
    return ap, bp, cp, pab, pbc


def build_a(base, cov, out, keep):
    ip = stage(base, "input_pair")

    # psrc_left/right are independent point coordinates now.
    ip["sweeps"].pop("psrc", None)
    ip.pop("derived", None)
    ip["devices"][0]["vds"] = "psrc_left-tail"
    ip["devices"][1]["vds"] = "psrc_right-tail"
    ip["outputs"] = {"tail": "tail"}
    ip["selection_coordinates"] = ["tail"]
    ip["diversity_keys"] = ["tail"]
    ip["global_cap"] = 64

    ts = stage(base, "tail_source")
    ts["global_cap"] = 64

    bindings = {
        "w1": {"column": "w_m1_um"},
        "i3_target": {"column": "i_m3_a"},
        "psrc_left": {"column": "vd1_v"},
        "psrc_right": {"column": "vd2_v"},
    }

    final = {
        "devices": [device(base, n) for n in ("M1", "M2", "M3")],
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

    return shell(
        base, "folded_component_A_independent_table", cov, out, keep,
        bindings, [ip, ts], final,
        {
            "w_m1_um": "w1",
            "i_m3_a": "i3_target",
            "vd1_v": "psrc_left",
            "vd2_v": "psrc_right",
            "tail_v": "tail",
            "vnb1_v": "vnb1",
            "w_m3_um": "w3",
        },
    )


def build_b(base, cov, out, keep):
    upper = stage(base, "upper_sources")
    upper["global_cap"] = 64

    folded = {
        "id": "folded_pair_fixed_interface",
        "sweeps": {
            "vpb2": {
                "source": "row_interval",
                "prefix": "vpb2_node",
                "unit": "v",
                "default_lo": 0.1,
                "default_hi": 1.7,
                "count": 41,
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
                "count": 60,
                "spacing": "geom",
            },
        },
        "devices": [
            {
                "name": "M6", "polarity": "pmos", "width": "w6",
                "vgs": "psrc_left-vpb2",
                "vds": "psrc_left-x",
                "vbs": "vdd-psrc_left",
            },
            {
                "name": "M7", "polarity": "pmos", "width": "w6",
                "vgs": "psrc_right-vpb2",
                "vds": "psrc_right-vout",
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
        "outputs": {"vpb2": "vpb2", "w6": "w6"},
        "selection_coordinates": ["vpb2", "w6"],
        "per_parent_keep": 3,
        "global_cap": 64,
        "diversity_keys": ["vpb2", "w6"],
    }

    bindings = {
        "i3_target": {"column": "i_m3_a"},
        "psrc_left": {"column": "vd1_v"},
        "psrc_right": {"column": "vd2_v"},
        "x": {"column": "vd6_v"},
        "vout": {"column": "vd7_v"},
    }

    final = {
        "devices": [device(base, n) for n in ("M4", "M5", "M6", "M7")],
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

    return shell(
        base, "folded_component_B_independent_table", cov, out, keep,
        bindings, [upper, folded], final,
        {
            "i_m3_a": "i3_target",
            "vd1_v": "psrc_left",
            "vd2_v": "psrc_right",
            "vd6_v": "x",
            "vd7_v": "vout",
            "vpb1_v": "vpb1",
            "w_m4_um": "w4",
            "vpb2_v": "vpb2",
            "w_m6_um": "w6",
        },
    )


def build_c(base, cov, out, keep):
    lower = {
        "id": "lower_sink_fixed_interface",
        "sweeps": {
            "nsink": {
                "source": "row_interval",
                "prefix": "nsink_left",
                "unit": "v",
                "default_lo": 0.02,
                "default_hi": 1.20,
                "count": 21,
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
                "count": 50,
                "spacing": "geom",
            },
        },
        "derived": {
            "nsink_left": "nsink",
            "nsink_right": "nsink",
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
        "id": "lower_cascode_pair_fixed_interface",
        "sweeps": {
            "vnb2": {
                "source": "row_interval",
                "prefix": "vnb2_node",
                "unit": "v",
                "default_lo": 0.1,
                "default_hi": 1.7,
                "count": 41,
                "spacing": "linear",
            },
        },
        "devices": [
            {
                "name": "M8", "polarity": "nmos", "width": "w8",
                "vgs": "vnb2-nsink_left",
                "vds": "x-nsink_left",
                "vbs": "nsink_left-vss",
            },
            {
                "name": "M9", "polarity": "nmos", "width": "w8",
                "vgs": "vnb2-nsink_right",
                "vds": "vout-nsink_right",
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
        "global_cap": 64,
        "diversity_keys": ["nsink_left", "w8", "vnb2"],
    }

    bindings = {
        "i3_target": {"column": "i_m3_a"},
        "x": {"column": "vd6_v"},
        "vout": {"column": "vd7_v"},
    }

    final = {
        "devices": [device(base, n) for n in ("M8", "M9", "M10", "M11")],
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

    return shell(
        base, "folded_component_C_independent_table", cov, out, keep,
        bindings, [lower, cascode], final,
        {
            "i_m3_a": "i3_target",
            "vd6_v": "x",
            "vd7_v": "vout",
            "nsink_left_v": "nsink_left",
            "nsink_right_v": "nsink_right",
            "w_m8_um": "w8",
            "vnb2_v": "vnb2",
        },
    )


def q(x: str) -> float:
    # Exact grids are written in decimal; round only to make CSV floating
    # representation harmless during dictionary joins.
    return round(float(x), 9)


def join_tables(a_rows, b_rows, c_rows):
    A = real_rows(a_rows)
    B = real_rows(b_rows)
    C = real_rows(c_rows)

    a_index = {}
    for a in A:
        key = (q(a["vd1_v"]), q(a["vd2_v"]))
        a_index.setdefault(key, []).append(a)

    c_index = {}
    for c in C:
        key = (q(c["vd6_v"]), q(c["vd7_v"]))
        c_index.setdefault(key, []).append(c)

    joined = []
    for b in B:
        kab = (q(b["vd1_v"]), q(b["vd2_v"]))
        kbc = (q(b["vd6_v"]), q(b["vd7_v"]))
        if kab not in a_index or kbc not in c_index:
            continue
        for a in a_index[kab]:
            for c in c_index[kbc]:
                joined.append({
                    "vd1_v": b["vd1_v"],
                    "vd2_v": b["vd2_v"],
                    "vd6_v": b["vd6_v"],
                    "vd7_v": b["vd7_v"],
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


def feasible_keys(rows, names):
    return {
        tuple(q(r[n]) for n in names)
        for r in real_rows(rows)
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--base-plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--w1", type=float, default=1.0)
    ap.add_argument("--i3-ua", type=float, default=10.0)
    ap.add_argument("--a-witnesses", type=int, default=8)
    ap.add_argument("--b-witnesses", type=int, default=8)
    ap.add_argument("--c-witnesses", type=int, default=8)
    args = ap.parse_args()

    root = args.root.resolve()
    absr = lambda p: p if p.is_absolute() else (root / p).resolve()
    base = read_yaml(absr(args.base_plan))
    engine = absr(args.engine)
    work = absr(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    i3 = args.i3_ua * 1e-6
    acov, bcov, ccov, pab, pbc = build_coverages(work, args.w1, i3)

    apath, aout = work/"A_plan.yaml", work/"A_table.csv"
    bpath, bout = work/"B_plan.yaml", work/"B_table.csv"
    cpath, cout = work/"C_plan.yaml", work/"C_table.csv"
    jout = work/"ABC_joined_witnesses.csv"

    write_yaml(apath, build_a(base, acov, aout, args.a_witnesses))
    write_yaml(bpath, build_b(base, bcov, bout, args.b_witnesses))
    write_yaml(cpath, build_c(base, ccov, cout, args.c_witnesses))

    print("\n===== INDEPENDENT TABLE A =====")
    run_engine(root, engine, apath, args.a_witnesses)

    print("\n===== INDEPENDENT TABLE B =====")
    run_engine(root, engine, bpath, args.b_witnesses)

    print("\n===== INDEPENDENT TABLE C =====")
    run_engine(root, engine, cpath, args.c_witnesses)

    ar = read_csv(aout)
    br = read_csv(bout)
    cr = read_csv(cout)

    joined = join_tables(ar, br, cr)
    write_csv(jout, joined)

    ak = feasible_keys(ar, ("vd1_v", "vd2_v"))
    bk_ab = feasible_keys(br, ("vd1_v", "vd2_v"))
    bk_bc = feasible_keys(br, ("vd6_v", "vd7_v"))
    ck = feasible_keys(cr, ("vd6_v", "vd7_v"))

    print("\n===== FOLDED INDEPENDENT COMPONENT TABLE JOIN =====")
    print(f"seed W1                    : {args.w1:.6g} um")
    print(f"seed I3                    : {args.i3_ua:.6g} uA")
    print(f"A/B shared voltage grid    : {pab}")
    print(f"B/C shared voltage grid    : {pbc}")
    print(f"A coverage rows            : {len(read_csv(acov))}")
    print(f"B coverage rows            : {len(read_csv(bcov))}")
    print(f"C coverage rows            : {len(read_csv(ccov))}")
    print(f"A witness rows             : {len(real_rows(ar))}")
    print(f"B witness rows             : {len(real_rows(br))}")
    print(f"C witness rows             : {len(real_rows(cr))}")
    print(f"A feasible (VD1,VD2) cells : {len(ak)}")
    print(f"B feasible AB cells        : {len(bk_ab)}")
    print(f"B feasible BC cells        : {len(bk_bc)}")
    print(f"C feasible (VD6,VD7) cells : {len(ck)}")
    print(f"A∩B AB-interface cells     : {len(ak & bk_ab)}")
    print(f"B∩C BC-interface cells     : {len(bk_bc & ck)}")
    print(f"Joined A+B+C witnesses     : {len(joined)}")
    print(f"\nA table : {aout}")
    print(f"B table : {bout}")
    print(f"C table : {cout}")
    print(f"JOINED  : {jout}")

    if not joined:
        print("\nNO FULL JOIN on this coarse 3x3 interface grid.")
        print("That would mean we densify the interface grid next; it would not")
        print("mean the component formulation failed.")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

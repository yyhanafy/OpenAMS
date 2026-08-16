#!/usr/bin/env python3
"""
Corrected two-stage A/B hierarchical interface experiment.

A = M1..M5
B = M6,M7

Electrical cut coordinates are ONLY:
    vy_v
    vbias_v

A independently tests the discrete (VY,VBIAS) cut grid for fixed (W1,I5).
Inside A:
    - VX follows the existing balanced two-stage relation VX=VY.
    - W3 and W5 are solved, not externally quantized.
    - A emits the exact continuous stage_ratio = 2*W3/W5.

B consumes each exact A interface state:
    (I5,VOUT,VY,VBIAS,stage_ratio)
and searches only its local realization W7, with W6=stage_ratio*W7.

This avoids the previous artificial quantization of stage_ratio.
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
    "examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml"
)
DEFAULT_ENGINE = Path("tools/validation/witness_engine.py")
DEFAULT_WORK = Path("runtime/two_stage_independent_component_tables_v2")


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
                fields.append(k)
                seen.add(k)
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


def pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    raise KeyError(f"none of {names!r} found; columns={sorted(row)}")


def real_rows(rows):
    return [
        r for r in rows
        if r.get("generation_status") == "WITNESS"
        and r.get("witness_rank") not in (None, "")
    ]


def linspace(lo: float, hi: float, n: int) -> list[float]:
    if n == 1:
        return [float(lo)]
    return [float(lo + i * (hi - lo) / (n - 1)) for i in range(n)]


def run_engine(root: Path, engine: Path, plan: Path, keep: int) -> None:
    cmd = [
        sys.executable, str(engine),
        "--plan", str(plan),
        "--root", str(root),
        "--witnesses-per-point", str(keep),
    ]
    print("\nRUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=root, check=True)


def build_a_coverage(
    path: Path,
    w1: float,
    i5: float,
    vy_count: int,
    vbias_count: int,
) -> tuple[list[float], list[float]]:
    vys = linspace(0.15, 1.65, vy_count)
    vbiases = linspace(0.55, 1.05, vbias_count)
    rows = []
    k = 0
    for vy in vys:
        for vbias in vbiases:
            rows.append({
                "point_index": k,
                "w_m1_um": w1,
                "i_m5_a": i5,
                "vy_v": vy,
                "vbias_v": vbias,
            })
            k += 1
    write_csv(path, rows)
    return vys, vbiases


def build_a_plan(base, coverage, output, keep):
    # M1/M2: cut voltage is independent; do NOT sweep vx.
    s1 = stage(base, "m1_input")
    s1["sweeps"].pop("vx", None)
    s1["derived"] = {"vx": "vy"}
    s1["outputs"] = {"vtail": "vtail"}
    s1["selection_coordinates"] = ["vtail"]
    s1["diversity_keys"] = ["vtail"]
    s1["global_cap"] = 64

    # M5: vbias is an independent cut voltage; solve only W5.
    s2 = stage(base, "m5_bias")
    s2["sweeps"].pop("vbias", None)
    s2["outputs"] = {"w5": "w5"}
    s2["selection_coordinates"] = ["w5"]
    s2["diversity_keys"] = ["vtail", "w5"]
    s2["global_cap"] = 64

    # M3: solve W3 normally.
    s3 = stage(base, "m3_load")
    s3["global_cap"] = 64

    # M2/M4: retain the existing balanced relation vy=vx.
    s4 = stage(base, "balanced_m2_m4")
    s4["global_cap"] = 64

    point_bindings = {
        "w1": {"column": "w_m1_um"},
        "i5_target": {"column": "i_m5_a"},
        "vy": {"column": "vy_v"},
        "vbias": {"column": "vbias_v"},
    }

    # Preserve any bound limits the original plan may use later in A.
    for key in ("vy_allowed_lo", "vy_allowed_hi"):
        if key in base.get("point_bindings", {}):
            point_bindings[key] = base["point_bindings"][key]

    return {
        "schema_version": base.get("schema_version", 1),
        "name": "two_stage_A_fixed_electrical_cut",
        "coverage_csv": str(coverage),
        "output_csv": str(output),
        "witnesses_per_point": keep,
        "sat_margin_v": base.get("sat_margin_v", 0.05),
        "mlp": copy.deepcopy(base["mlp"]),
        "constants": copy.deepcopy(base["constants"]),
        "point_bindings": point_bindings,
        "derived_bindings": {"ib": "0.5*i5_target", "vx": "vy"},
        "stages": [s1, s2, s3, s4],
        "final": {
            "devices": [device(base, n) for n in ("M1","M2","M3","M4","M5")],
            "residuals": {
                k: copy.deepcopy(base["final"]["residuals"][k])
                for k in ("tail_kcl","x_kcl","y_kcl","mirror_balance","i5_target")
            },
            "saturation_headroom": {
                k: copy.deepcopy(base["final"]["saturation_headroom"][k])
                for k in ("M1","M2","M3","M4","M5")
            },
            "constraints": [
                "M1_domain & M2_domain & M3_domain & M4_domain & M5_domain",
                "((vx-vtail)-M1_vdsat)>=sat_margin_v",
                "((vy-vtail)-M2_vdsat)>=sat_margin_v",
                "((vdd-vx)-M3_vdsat)>=sat_margin_v",
                "((vdd-vy)-M4_vdsat)>=sat_margin_v",
                "((vtail-vss)-M5_vdsat)>=sat_margin_v",
            ],
        },
        "csv_aliases": {
            "w_m1_um": "w1",
            "i_m5_target_a": "i5_target",
            "vy_v": "vy",
            "vbias_v": "vbias",
            "vtail_v": "vtail",
            "vx_v": "vx",
            "w_m3_um": "w3",
            "w_m5_um": "w5",
        },
    }


def make_b_coverage(a_rows, path: Path, vout: float):
    out = []
    for hidx, a in enumerate(real_rows(a_rows)):
        w3 = float(pick(a, "w_m3_um", "w3"))
        w5 = float(pick(a, "w_m5_um", "w5"))
        ratio = 2.0 * w3 / w5
        out.append({
            "point_index": hidx,
            "a_point_index": int(float(pick(a, "point_index"))),
            "a_witness_rank": int(float(pick(a, "witness_rank"))),
            "i_m5_a": float(pick(a, "i_m5_target_a", "i5_target", "i_m5_a")),
            "vy_v": float(pick(a, "vy_v", "vy")),
            "vbias_v": float(pick(a, "vbias_v", "vbias")),
            "stage_ratio": ratio,
            "vout_v": vout,
            "w_m3_um": w3,
            "w_m5_um": w5,
        })
    write_csv(path, out)
    return out


def build_b_plan(base, coverage, output, keep):
    s = stage(base, "output_m6_m7")

    # VOUT is an independent input to component B.
    # Do not allow the inherited full-circuit stage to sweep/overwrite it.
    s["sweeps"].pop("vout", None)

    # Replace the original derived width rule by the exact ratio emitted by A.
    # Keep B local: search W7 and derive W6=R*W7.
    s["derived"] = {"w6": "stage_ratio*w7"}

    bindings = {
        "i5_target": {"column": "i_m5_a"},
        "vy": {"column": "vy_v"},
        "vbias": {"column": "vbias_v"},
        "stage_ratio": {"column": "stage_ratio"},
        "vout": {"column": "vout_v"},
        "w3": {"column": "w_m3_um"},
        "w5": {"column": "w_m5_um"},
        "a_point_index": {"column": "a_point_index"},
        "a_witness_rank": {"column": "a_witness_rank"},
    }
    for key in ("w6_allowed_lo", "w6_allowed_hi"):
        if key in base.get("point_bindings", {}):
            bindings[key] = copy.deepcopy(base["point_bindings"][key])

    return {
        "schema_version": base.get("schema_version", 1),
        "name": "two_stage_B_exact_A_interface",
        "coverage_csv": str(coverage),
        "output_csv": str(output),
        "witnesses_per_point": keep,
        "sat_margin_v": base.get("sat_margin_v", 0.05),
        "mlp": copy.deepcopy(base["mlp"]),
        "constants": copy.deepcopy(base["constants"]),
        "point_bindings": bindings,
        "derived_bindings": {},
        "stages": [s],
        "final": {
            "devices": [device(base, "M6"), device(base, "M7")],
            "residuals": {
                "output_kcl": copy.deepcopy(base["final"]["residuals"]["output_kcl"])
            },
            "saturation_headroom": {
                "M6": copy.deepcopy(base["final"]["saturation_headroom"]["M6"]),
                "M7": copy.deepcopy(base["final"]["saturation_headroom"]["M7"]),
            },
            "constraints": [
                "M6_domain & M7_domain",
                "((vdd-vout)-M6_vdsat)>=sat_margin_v",
                "((vout-vss)-M7_vdsat)>=sat_margin_v",
            ],
        },
        "csv_aliases": {
            "a_point_index": "a_point_index",
            "a_witness_rank": "a_witness_rank",
            "i_m5_a": "i5_target",
            "vy_v": "vy",
            "vbias_v": "vbias",
            "stage_ratio": "stage_ratio",
            "vout_v": "vout",
            "w_m6_um": "w6",
            "w_m7_um": "w7",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--base-plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--w1", type=float, default=25.75)
    ap.add_argument("--i5-ua", type=float, default=32.5)
    ap.add_argument("--vout", type=float, default=1.36)
    ap.add_argument("--vy-count", type=int, default=11)
    ap.add_argument("--vbias-count", type=int, default=9)
    ap.add_argument("--a-witnesses", type=int, default=5)
    ap.add_argument("--b-witnesses", type=int, default=3)
    args = ap.parse_args()

    root = args.root.resolve()
    absr = lambda p: p if p.is_absolute() else (root / p).resolve()
    base = read_yaml(absr(args.base_plan))
    engine = absr(args.engine)
    work = absr(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    acov = work / "A_coverage.csv"
    aout = work / "A_table.csv"
    aplan = work / "A_plan.yaml"
    bcov = work / "B_coverage.csv"
    bout = work / "B_table.csv"
    bplan = work / "B_plan.yaml"

    vys, vbiases = build_a_coverage(
        acov, args.w1, args.i5_ua * 1e-6, args.vy_count, args.vbias_count
    )
    write_yaml(aplan, build_a_plan(base, acov, aout, args.a_witnesses))

    print("===== COMPONENT A: M1-M5 =====")
    print(f"electrical cut grid: VY({len(vys)}) x VBIAS({len(vbiases)}) = {len(vys)*len(vbiases)}")
    run_engine(root, engine, aplan, args.a_witnesses)

    A_rows = read_csv(aout)
    A_real = real_rows(A_rows)
    A_cells = {
        (
            round(float(pick(r, "vy_v", "vy")), 9),
            round(float(pick(r, "vbias_v", "vbias")), 9),
        )
        for r in A_real
    }

    B_cov = make_b_coverage(A_rows, bcov, args.vout)
    if not B_cov:
        print("\nComponent A produced no realizable interface states.")
        return 4

    write_yaml(bplan, build_b_plan(base, bcov, bout, args.b_witnesses))

    print("\n===== COMPONENT B: M6-M7 =====")
    print(f"exact A interface states passed to B: {len(B_cov)}")
    run_engine(root, engine, bplan, args.b_witnesses)

    B_rows = read_csv(bout)
    B_real = real_rows(B_rows)

    surviving_a_states = {
        (
            int(float(pick(r, "a_point_index"))),
            int(float(pick(r, "a_witness_rank"))),
        )
        for r in B_real
    }

    joined = []
    for r in B_real:
        joined.append({
            "a_point_index": int(float(pick(r, "a_point_index"))),
            "a_witness_rank": int(float(pick(r, "a_witness_rank"))),
            "b_witness_rank": int(float(pick(r, "witness_rank"))),
            "vy_v": float(pick(r, "vy_v", "vy")),
            "vbias_v": float(pick(r, "vbias_v", "vbias")),
            "stage_ratio": float(pick(r, "stage_ratio")),
            "vout_v": float(pick(r, "vout_v", "vout")),
            "w_m6_um": float(pick(r, "w_m6_um", "w6")),
            "w_m7_um": float(pick(r, "w_m7_um", "w7")),
        })
    write_csv(work / "AB_joined.csv", joined)

    print("\n===== CORRECTED TWO-STAGE A/B JOIN =====")
    print(f"W1 / I5 / VOUT                 : {args.w1:.6g} um / {args.i5_ua:.6g} uA / {args.vout:.6g} V")
    print(f"A electrical interface cells   : {len(A_cells)}/{len(vys)*len(vbiases)}")
    print(f"A realizations emitted          : {len(A_real)}")
    print(f"B exact input states            : {len(B_cov)}")
    print(f"B surviving A states            : {len(surviving_a_states)}")
    print(f"A+B witness rows                : {len(joined)}")
    if B_cov:
        print(f"A->B state survival             : {100.0*len(surviving_a_states)/len(B_cov):.2f}%")

    if joined:
        print("\nfirst joined states:")
        for r in joined[:20]:
            print(
                f"  VY={r['vy_v']:.6f}  "
                f"VBIAS={r['vbias_v']:.6f}  "
                f"R={r['stage_ratio']:.6f}  "
                f"W6={r['w_m6_um']:.6f}  W7={r['w_m7_um']:.6f}"
            )

    print(f"\nA table : {aout}")
    print(f"B input : {bcov}")
    print(f"B table : {bout}")
    print(f"JOINED  : {work/'AB_joined.csv'}")
    return 0 if joined else 5


if __name__ == "__main__":
    raise SystemExit(main())

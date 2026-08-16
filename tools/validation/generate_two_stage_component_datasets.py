#!/usr/bin/env python3
"""
Generate two-stage component-MLP training datasets from the corrected A/B teacher.

A model target:
    inputs  = W1, I5, VY, VBIAS
    outputs = feasibility, feasible R envelope [Rmin,Rmax]
where R = 2*W3/W5.

B model target:
    inputs  = I5, VOUT, VY, VBIAS, R
    output  = feasibility

The teacher remains the existing transistor-MLP witness engine.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("two_stage_teacher", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                fields.append(k)
                seen.add(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def evenly_pick(lo, hi, count):
    return np.linspace(float(lo), float(hi), int(count)).tolist()


def run_quiet(root, engine, plan, keep, log):
    cmd = [
        sys.executable, str(engine),
        "--plan", str(plan),
        "--root", str(root),
        "--witnesses-per-point", str(keep),
    ]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as f:
        subprocess.run(
            cmd, cwd=root, stdout=f, stderr=subprocess.STDOUT, check=True
        )


def witness_rows(rows):
    return [
        r for r in rows
        if r.get("generation_status") == "WITNESS"
        and r.get("witness_rank") not in (None, "")
    ]


def f(row, *names):
    for name in names:
        if row.get(name) not in (None, ""):
            return float(row[name])
    raise KeyError((names, sorted(row)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument(
        "--teacher-script",
        type=Path,
        default=Path("tools/validation/run_two_stage_independent_tables_v2.py"),
    )
    ap.add_argument(
        "--engine",
        type=Path,
        default=Path("tools/validation/witness_engine.py"),
    )
    ap.add_argument(
        "--base-plan",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml"),
    )
    ap.add_argument(
        "--work-dir",
        type=Path,
        default=Path("runtime/two_stage_component_training"),
    )
    ap.add_argument("--w1-samples", type=int, default=5)
    ap.add_argument("--i5-samples", type=int, default=5)
    ap.add_argument("--w1-min-um", type=float, default=1.0)
    ap.add_argument("--w1-max-um", type=float, default=100.0)
    ap.add_argument("--i5-min-ua", type=float, default=10.009030134)
    ap.add_argument("--i5-max-ua", type=float, default=99.956552025)
    ap.add_argument("--vout", type=float, default=1.36)
    ap.add_argument("--vy-count", type=int, default=121)
    ap.add_argument("--vbias-count", type=int, default=9)
    ap.add_argument("--a-witnesses", type=int, default=5)
    ap.add_argument("--b-witnesses", type=int, default=3)
    args = ap.parse_args()

    root = args.root.resolve()
    absr = lambda p: p if p.is_absolute() else (root / p).resolve()
    teacher = load_module(absr(args.teacher_script))
    engine = absr(args.engine)
    base = teacher.read_yaml(absr(args.base_plan))
    work = absr(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    w1_values = evenly_pick(args.w1_min_um, args.w1_max_um, args.w1_samples)
    i5_values_ua = evenly_pick(args.i5_min_ua, args.i5_max_ua, args.i5_samples)

    A_dataset = []
    B_dataset = []

    total = len(w1_values) * len(i5_values_ua)
    seq = 0

    for wi, w1 in enumerate(w1_values):
        for ii, i5_ua in enumerate(i5_values_ua):
            seq += 1
            i5 = i5_ua * 1e-6
            case = work / "oracle" / f"w{wi:02d}_i{ii:02d}"
            case.mkdir(parents=True, exist_ok=True)

            acov = case / "A_coverage.csv"
            aout = case / "A_table.csv"
            aplan = case / "A_plan.yaml"

            teacher.build_a_coverage(
                acov, w1, i5, args.vy_count, args.vbias_count
            )
            teacher.write_yaml(
                aplan,
                teacher.build_a_plan(base, acov, aout, args.a_witnesses),
            )
            run_quiet(
                root, engine, aplan, args.a_witnesses, case / "A_engine.log"
            )

            cov_rows = read_csv(acov)
            a_rows = read_csv(aout)
            a_real = witness_rows(a_rows)

            # Group A realizations by original electrical cut cell.
            by_point = {}
            for r in a_real:
                pi = int(float(r["point_index"]))
                w3 = f(r, "w_m3_um", "w3")
                w5 = f(r, "w_m5_um", "w5")
                ratio = 2.0 * w3 / w5
                by_point.setdefault(pi, []).append(ratio)

            for r in cov_rows:
                pi = int(float(r["point_index"]))
                ratios = by_point.get(pi, [])
                A_dataset.append({
                    "group_id": f"w{wi:02d}_i{ii:02d}",
                    "w_m1_um": float(r["w_m1_um"]),
                    "i_m5_a": float(r["i_m5_a"]),
                    "vy_v": float(r["vy_v"]),
                    "vbias_v": float(r["vbias_v"]),
                    "valid": int(bool(ratios)),
                    "r_count": len(ratios),
                    "r_min": min(ratios) if ratios else "",
                    "r_max": max(ratios) if ratios else "",
                })

            # B is generated only from exact A realizations, as in the
            # validated corrected hierarchy.
            bcov = case / "B_coverage.csv"
            bout = case / "B_table.csv"
            bplan = case / "B_plan.yaml"

            b_cov_rows = teacher.make_b_coverage(a_rows, bcov, args.vout)

            if b_cov_rows:
                teacher.write_yaml(
                    bplan,
                    teacher.build_b_plan(
                        base, bcov, bout, args.b_witnesses
                    ),
                )
                run_quiet(
                    root, engine, bplan, args.b_witnesses,
                    case / "B_engine.log",
                )
                b_out_rows = read_csv(bout)
                valid_b_points = {
                    int(float(r["point_index"]))
                    for r in witness_rows(b_out_rows)
                }

                for r in b_cov_rows:
                    pi = int(float(r["point_index"]))
                    B_dataset.append({
                        "group_id": f"w{wi:02d}_i{ii:02d}",
                        "source_w_m1_um": w1,
                        "i_m5_a": float(r["i_m5_a"]),
                        "vout_v": float(r["vout_v"]),
                        "vy_v": float(r["vy_v"]),
                        "vbias_v": float(r["vbias_v"]),
                        "stage_ratio": float(r["stage_ratio"]),
                        "valid": int(pi in valid_b_points),
                    })

            a_valid_cells = sum(
                1 for x in A_dataset
                if x["group_id"] == f"w{wi:02d}_i{ii:02d}" and x["valid"]
            )
            b_case = [
                x for x in B_dataset
                if x["group_id"] == f"w{wi:02d}_i{ii:02d}"
            ]
            b_valid = sum(x["valid"] for x in b_case)
            print(
                f"[{seq:2d}/{total}] "
                f"W1={w1:7.3f} um I5={i5_ua:8.3f} uA  "
                f"A={a_valid_cells:4d}/{args.vy_count*args.vbias_count}  "
                f"B={b_valid:4d}/{len(b_case):4d}",
                flush=True,
            )

    outdir = work / "datasets"
    A_path = outdir / "A_dataset.csv"
    B_path = outdir / "B_dataset.csv"
    write_csv(A_path, A_dataset)
    write_csv(B_path, B_dataset)

    print("\n===== TWO-STAGE COMPONENT DATASET SUMMARY =====")
    print("W1 samples (um):", [round(x, 6) for x in w1_values])
    print("I5 samples (uA):", [round(x, 6) for x in i5_values_ua])
    print(
        f"A rows={len(A_dataset)} "
        f"valid={sum(x['valid'] for x in A_dataset)} "
        f"invalid={sum(1-x['valid'] for x in A_dataset)}"
    )
    print(
        f"B rows={len(B_dataset)} "
        f"valid={sum(x['valid'] for x in B_dataset)} "
        f"invalid={sum(1-x['valid'] for x in B_dataset)}"
    )
    print("A:", A_path)
    print("B:", B_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

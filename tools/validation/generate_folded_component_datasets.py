#!/usr/bin/env python3
"""
Generate labeled folded-cascode component-feasibility datasets.

Teacher/oracle:
    existing transistor-level MLP witness engine

Inputs are taken from the Step-3 independent-domain artifact plus the
Step-4 hierarchical component contract.

Outputs:
    A_dataset.csv : w_m1_um, i_m3_a, vp_v, valid, witness_count
    B_dataset.csv : i_m3_a, vp_v, vx_v, valid, witness_count
    C_dataset.csv : i_m3_a, vx_v, valid, witness_count

This is training-data generation only.  The component MLPs are trained
separately.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("folded_teacher", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import helper module {path}")
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
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def evenly_pick(values, count):
    values = list(values)
    if len(values) <= count:
        return values
    idx = np.linspace(0, len(values) - 1, count)
    idx = np.rint(idx).astype(int)
    return [values[i] for i in idx]


def run_quiet(root: Path, engine: Path, plan: Path, keep: int, log: Path):
    cmd = [
        sys.executable, str(engine),
        "--plan", str(plan),
        "--root", str(root),
        "--witnesses-per-point", str(keep),
    ]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as f:
        subprocess.run(
            cmd,
            cwd=root,
            stdout=f,
            stderr=subprocess.STDOUT,
            check=True,
        )


def label_coverage(coverage_path: Path, output_path: Path):
    cov = read_csv(coverage_path)
    out = read_csv(output_path)

    counts = {}
    for row in out:
        pi = int(float(row["point_index"]))
        if row.get("generation_status") == "WITNESS":
            counts[pi] = counts.get(pi, 0) + 1

    labeled = []
    for row in cov:
        pi = int(float(row["point_index"]))
        item = dict(row)
        item["valid"] = 1 if counts.get(pi, 0) > 0 else 0
        item["witness_count"] = counts.get(pi, 0)
        labeled.append(item)
    return labeled


def contract_grid(contract, coordinate):
    for interface in contract["interfaces"]:
        for coord in interface["coordinates"]:
            if coord["name"] == coordinate:
                return coord["grid"]
    raise KeyError(coordinate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "examples/folded_cascode/generated/assignment_synthesis/"
            "hierarchical_component_contract.json"
        ),
    )
    ap.add_argument(
        "--teacher-script",
        type=Path,
        default=Path("tools/validation/run_folded_balanced_current_derived.py"),
    )
    ap.add_argument(
        "--engine",
        type=Path,
        default=Path("tools/validation/witness_engine.py"),
    )
    ap.add_argument(
        "--work-dir",
        type=Path,
        default=Path("runtime/folded_component_training"),
    )
    ap.add_argument("--w1-samples", type=int, default=5)
    ap.add_argument("--i3-samples", type=int, default=5)
    ap.add_argument("--w1-min-um", type=float, default=1.0)
    ap.add_argument("--w1-max-um", type=float, default=100.0)
    ap.add_argument("--i3-min-ua", type=float, default=10.0)
    ap.add_argument("--i3-max-ua", type=float, default=100.0)
    ap.add_argument("--teacher-witnesses", type=int, default=3)
    args = ap.parse_args()

    root = args.root.resolve()
    absr = lambda p: p if p.is_absolute() else (root / p).resolve()

    contract = json.loads(absr(args.contract).read_text())
    teacher = load_module(absr(args.teacher_script))
    engine = absr(args.engine)
    work = absr(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    vp_grid = contract_grid(contract, "vp_v")
    vx_grid = contract_grid(contract, "vx_v")
    vp_count = int(vp_grid["count"])
    vx_count = int(vx_grid["count"])

    # The cleaned folded flow currently has no normalized Step-3
    # independent_regions.json artifact.  Sample the declared synthesis
    # independent domains directly for this first component-MLP build.
    w1_values = np.linspace(
        args.w1_min_um,
        args.w1_max_um,
        args.w1_samples,
    ).tolist()

    i3_values = (
        np.linspace(
            args.i3_min_ua,
            args.i3_max_ua,
            args.i3_samples,
        ) * 1e-6
    ).tolist()

    base = teacher.load_yaml(absr(teacher.DEFAULT_PLAN))

    A_all = []
    B_all = []
    C_all = []

    # ---------- A ----------
    print("===== GENERATING A DATASET =====")
    total_a = len(w1_values) * len(i3_values)
    n = 0
    for w1 in w1_values:
        for i3 in i3_values:
            n += 1
            seed = work / "oracle" / "A" / f"w1_{w1:.6g}_i3_{i3:.12g}"
            seed.mkdir(parents=True, exist_ok=True)

            acov, _, _, _, _ = teacher.build_coverages(
                seed, w1, i3, vp_count, vx_count
            )
            plan = seed / "plan.yaml"
            out = seed / "table.csv"
            teacher.save_yaml(
                plan,
                teacher.build_A(
                    base, acov, out, args.teacher_witnesses
                ),
            )
            run_quiet(
                root, engine, plan, args.teacher_witnesses, seed / "engine.log"
            )
            labeled = label_coverage(acov, out)
            for r in labeled:
                A_all.append({
                    "w_m1_um": float(r["w_m1_um"]),
                    "i_m3_a": float(r["i_m3_a"]),
                    "vp_v": float(r["vp_v"]),
                    "valid": int(r["valid"]),
                    "witness_count": int(r["witness_count"]),
                })
            print(
                f"A {n:2d}/{total_a}: W1={w1:7.3f} um "
                f"I3={i3*1e6:8.3f} uA "
                f"valid={sum(x['valid'] for x in labeled):2d}/{len(labeled)}"
            )

    # ---------- B and C ----------
    print("\n===== GENERATING B/C DATASETS =====")
    for n, i3 in enumerate(i3_values, 1):
        seed = work / "oracle" / "BC" / f"i3_{i3:.12g}"
        seed.mkdir(parents=True, exist_ok=True)

        _, bcov, ccov, _, _ = teacher.build_coverages(
            seed, w1_values[0], i3, vp_count, vx_count
        )

        bplan = seed / "B_plan.yaml"
        bout = seed / "B_table.csv"
        teacher.save_yaml(
            bplan,
            teacher.build_B(
                base, bcov, bout, args.teacher_witnesses
            ),
        )
        run_quiet(
            root, engine, bplan, args.teacher_witnesses, seed / "B_engine.log"
        )
        b_labeled = label_coverage(bcov, bout)
        for r in b_labeled:
            B_all.append({
                "i_m3_a": float(r["i_m3_a"]),
                "vp_v": float(r["vp_v"]),
                "vx_v": float(r["vx_v"]),
                "valid": int(r["valid"]),
                "witness_count": int(r["witness_count"]),
            })

        cplan = seed / "C_plan.yaml"
        cout = seed / "C_table.csv"
        teacher.save_yaml(
            cplan,
            teacher.build_C(
                base, ccov, cout, args.teacher_witnesses
            ),
        )
        run_quiet(
            root, engine, cplan, args.teacher_witnesses, seed / "C_engine.log"
        )
        c_labeled = label_coverage(ccov, cout)
        for r in c_labeled:
            C_all.append({
                "i_m3_a": float(r["i_m3_a"]),
                "vx_v": float(r["vx_v"]),
                "valid": int(r["valid"]),
                "witness_count": int(r["witness_count"]),
            })

        print(
            f"I3 {n:2d}/{len(i3_values)}: {i3*1e6:8.3f} uA  "
            f"B valid={sum(x['valid'] for x in b_labeled):3d}/{len(b_labeled)}  "
            f"C valid={sum(x['valid'] for x in c_labeled):2d}/{len(c_labeled)}"
        )

    outdir = work / "datasets"
    A_path = outdir / "A_dataset.csv"
    B_path = outdir / "B_dataset.csv"
    C_path = outdir / "C_dataset.csv"
    write_csv(A_path, A_all)
    write_csv(B_path, B_all)
    write_csv(C_path, C_all)

    def summary(name, rows):
        valid = sum(r["valid"] for r in rows)
        print(
            f"{name}: rows={len(rows)} valid={valid} "
            f"invalid={len(rows)-valid} "
            f"positive_rate={100.0*valid/max(len(rows),1):.2f}%"
        )

    print("\n===== DATASET SUMMARY =====")
    print("W1 samples (um):", [round(x, 6) for x in w1_values])
    print("I3 samples (uA):", [round(x*1e6, 6) for x in i3_values])
    summary("A", A_all)
    summary("B", B_all)
    summary("C", C_all)
    print("A:", A_path)
    print("B:", B_path)
    print("C:", C_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

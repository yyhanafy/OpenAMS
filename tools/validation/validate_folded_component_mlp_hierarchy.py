#!/usr/bin/env python3
"""
Compare the trained folded-cascode component MLP hierarchy against the
device-MLP teacher on one unseen (W1, I3) point.

Outputs:
  - teacher masks for A/B/C
  - predicted masks for A/B/C
  - per-component confusion metrics
  - teacher vs MLP joined feasible interface cells
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
from pathlib import Path

import numpy as np
import torch
from torch import nn


class MLP(nn.Module):
    def __init__(self, nin, hidden):
        super().__init__()
        layers = []
        d = nin
        for h in hidden:
            layers += [nn.Linear(d, h), nn.ReLU()]
            d = h
        layers.append(nn.Linear(d, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x).squeeze(-1)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("teacher_mod", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_checkpoint(path: Path):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    model = MLP(len(ckpt["feature_names"]), ckpt["hidden"])
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return ckpt, model


def predict_rows(rows, ckpt, model):
    X = np.asarray(
        [[float(r[f]) for f in ckpt["feature_names"]] for r in rows],
        dtype=np.float32,
    )
    mean = np.asarray(ckpt["mean"], dtype=np.float32)
    std = np.asarray(ckpt["std"], dtype=np.float32)
    Xn = (X - mean) / std
    with torch.no_grad():
        p = torch.sigmoid(model(torch.tensor(Xn))).numpy()
    pred = (p >= float(ckpt["threshold"])).astype(int)
    return p, pred


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def real(rows):
    return [
        r for r in rows
        if r.get("generation_status") == "WITNESS"
        and r.get("witness_rank") not in (None, "")
    ]


def label_coverage(cov_rows, out_rows):
    valid_points = {
        int(float(r["point_index"]))
        for r in out_rows
        if r.get("generation_status") == "WITNESS"
    }
    return np.asarray(
        [1 if int(float(r["point_index"])) in valid_points else 0 for r in cov_rows],
        dtype=int,
    )


def confusion(y, pred):
    tp = int(np.sum((y == 1) & (pred == 1)))
    tn = int(np.sum((y == 0) & (pred == 0)))
    fp = int(np.sum((y == 0) & (pred == 1)))
    fn = int(np.sum((y == 1) & (pred == 0)))
    recall = tp / max(tp + fn, 1)
    precision = tp / max(tp + fp, 1)
    return tp, tn, fp, fn, recall, precision


def q(v):
    return round(float(v), 9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--w1", type=float, default=38.125)
    ap.add_argument("--i3-ua", type=float, default=43.75)
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
        default=Path("runtime/folded_component_mlp_validation"),
    )
    ap.add_argument(
        "--model-a",
        type=Path,
        default=Path("technology/component_models/folded_input_tail_network.pt"),
    )
    ap.add_argument(
        "--model-b",
        type=Path,
        default=Path("technology/component_models/folded_upper_folded_network.pt"),
    )
    ap.add_argument(
        "--model-c",
        type=Path,
        default=Path("technology/component_models/folded_lower_output_network.pt"),
    )
    args = ap.parse_args()

    root = args.root.resolve()
    absr = lambda p: p if p.is_absolute() else (root / p).resolve()

    teacher = load_module(absr(args.teacher_script))
    work = absr(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    i3 = args.i3_ua * 1e-6
    acov, bcov, ccov, vp_grid, vx_grid = teacher.build_coverages(
        work, args.w1, i3, 31, 21
    )

    base = teacher.load_yaml(absr(teacher.DEFAULT_PLAN))
    engine = absr(args.engine)

    aplan, aout = work/"A_plan.yaml", work/"A_teacher.csv"
    bplan, bout = work/"B_plan.yaml", work/"B_teacher.csv"
    cplan, cout = work/"C_plan.yaml", work/"C_teacher.csv"

    teacher.save_yaml(aplan, teacher.build_A(base, acov, aout, 3))
    teacher.save_yaml(bplan, teacher.build_B(base, bcov, bout, 3))
    teacher.save_yaml(cplan, teacher.build_C(base, ccov, cout, 3))

    teacher.run_engine(root, engine, aplan, 3)
    teacher.run_engine(root, engine, bplan, 3)
    teacher.run_engine(root, engine, cplan, 3)

    A_cov, B_cov, C_cov = read_csv(acov), read_csv(bcov), read_csv(ccov)
    A_out, B_out, C_out = read_csv(aout), read_csv(bout), read_csv(cout)

    yA = label_coverage(A_cov, A_out)
    yB = label_coverage(B_cov, B_out)
    yC = label_coverage(C_cov, C_out)

    ckA, mA = load_checkpoint(absr(args.model_a))
    ckB, mB = load_checkpoint(absr(args.model_b))
    ckC, mC = load_checkpoint(absr(args.model_c))

    _, pA = predict_rows(A_cov, ckA, mA)
    _, pB = predict_rows(B_cov, ckB, mB)
    _, pC = predict_rows(C_cov, ckC, mC)

    # Build teacher and MLP feasible interface sets.
    teacher_A = {q(r["vp_v"]) for r, y in zip(A_cov, yA) if y}
    teacher_B = {(q(r["vp_v"]), q(r["vx_v"])) for r, y in zip(B_cov, yB) if y}
    teacher_C = {q(r["vx_v"]) for r, y in zip(C_cov, yC) if y}
    teacher_join = {(vp, vx) for vp, vx in teacher_B if vp in teacher_A and vx in teacher_C}

    pred_A = {q(r["vp_v"]) for r, y in zip(A_cov, pA) if y}
    pred_B = {(q(r["vp_v"]), q(r["vx_v"])) for r, y in zip(B_cov, pB) if y}
    pred_C = {q(r["vx_v"]) for r, y in zip(C_cov, pC) if y}
    pred_join = {(vp, vx) for vp, vx in pred_B if vp in pred_A and vx in pred_C}

    join_tp = len(teacher_join & pred_join)
    join_fn = len(teacher_join - pred_join)
    join_fp = len(pred_join - teacher_join)
    join_recall = join_tp / max(len(teacher_join), 1)
    join_precision = join_tp / max(len(pred_join), 1)

    print("\n===== UNSEEN-POINT COMPONENT MLP VALIDATION =====")
    print(f"W1 = {args.w1:.6g} um")
    print(f"I3 = {args.i3_ua:.6g} uA")

    for name, y, p in (("A", yA, pA), ("B", yB, pB), ("C", yC, pC)):
        tp, tn, fp, fn, recall, precision = confusion(y, p)
        print(
            f"{name}: teacher_valid={int(y.sum())}/{len(y)}  "
            f"TP/TN/FP/FN={tp}/{tn}/{fp}/{fn}  "
            f"recall={recall:.4f} precision={precision:.4f}"
        )

    print("\n===== JOIN COMPARISON =====")
    print(f"teacher joined interface cells : {len(teacher_join)}")
    print(f"MLP joined interface cells     : {len(pred_join)}")
    print(f"join TP / FP / FN              : {join_tp} / {join_fp} / {join_fn}")
    print(f"join recall                    : {join_recall:.4f}")
    print(f"join precision                 : {join_precision:.4f}")

    if teacher_join:
        print("\nteacher join cells:")
        for vp, vx in sorted(teacher_join):
            mark = "RECOVERED" if (vp, vx) in pred_join else "MISSED"
            print(f"  VP={vp:.6f}  VX={vx:.6f}  {mark}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

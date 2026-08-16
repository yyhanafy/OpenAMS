#!/usr/bin/env python3
"""
Benchmark ONLY the runtime of the folded-cascode hierarchical component-MLP search.

No witness engine.
No transistor/device MLP teacher.
No ngspice.

For each independent design point (W1, I3), evaluate:
    A over 31 VP points
    B over 31 x 21 = 651 (VP,VX) points
    C over 21 VX points
then perform the Boolean interface join.

Reports:
    model load time
    single-point inference time
    average per-point time over a batch
    throughput in independent design points / second
"""
from __future__ import annotations

import argparse
import time
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


def load_model(path: Path):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    model = MLP(len(ckpt["feature_names"]), ckpt["hidden"])
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    mean = torch.tensor(np.asarray(ckpt["mean"], dtype=np.float32))
    std = torch.tensor(np.asarray(ckpt["std"], dtype=np.float32))
    threshold = float(ckpt["threshold"])
    return ckpt, model, mean, std, threshold


def linspace(lo, hi, n):
    return np.linspace(lo, hi, n, dtype=np.float32)


def eval_component(model, mean, std, threshold, X):
    X = (X - mean) / std
    with torch.inference_mode():
        p = torch.sigmoid(model(X))
    return p >= threshold


def make_grids(vp_count=31, vx_count=21):
    vp = torch.tensor(linspace(0.001, 1.799, vp_count))
    vx = torch.tensor(linspace(0.05, 1.75, vx_count))
    return vp, vx


def run_one(w1_um, i3_ua, vp, vx, A, B, C):
    ckA, mA, muA, sdA, thA = A
    ckB, mB, muB, sdB, thB = B
    ckC, mC, muC, sdC, thC = C

    i3_a = np.float32(i3_ua * 1e-6)
    w1 = np.float32(w1_um)

    # A: [W1, I3, VP]
    XA = torch.column_stack([
        torch.full_like(vp, w1),
        torch.full_like(vp, i3_a),
        vp,
    ])

    # B: [I3, VP, VX]
    VP, VX = torch.meshgrid(vp, vx, indexing="ij")
    XB = torch.column_stack([
        torch.full((VP.numel(),), i3_a, dtype=torch.float32),
        VP.reshape(-1),
        VX.reshape(-1),
    ])

    # C: [I3, VX]
    XC = torch.column_stack([
        torch.full_like(vx, i3_a),
        vx,
    ])

    maskA = eval_component(mA, muA, sdA, thA, XA)
    maskB = eval_component(mB, muB, sdB, thB, XB).reshape(len(vp), len(vx))
    maskC = eval_component(mC, muC, sdC, thC, XC)

    joined = maskB & maskA[:, None] & maskC[None, :]
    return int(maskA.sum()), int(maskB.sum()), int(maskC.sum()), int(joined.sum())


def run_batch(w1_values, i3_values_ua, vp, vx, A, B, C):
    # Simple loop over independent design points, but models stay loaded.
    # This isolates realistic Step-5 overhead without teacher work.
    results = []
    for w1, i3 in zip(w1_values, i3_values_ua):
        results.append(run_one(w1, i3, vp, vx, A, B, C))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--w1", type=float, default=38.125)
    ap.add_argument("--i3-ua", type=float, default=43.75)
    ap.add_argument("--batch-points", type=int, default=1000)
    ap.add_argument("--repeats", type=int, default=5)
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

    torch.set_num_threads(1)

    t0 = time.perf_counter()
    A = load_model(absr(args.model_a))
    B = load_model(absr(args.model_b))
    C = load_model(absr(args.model_c))
    load_s = time.perf_counter() - t0

    vp, vx = make_grids()

    # Warm-up
    for _ in range(20):
        run_one(args.w1, args.i3_ua, vp, vx, A, B, C)

    single_times = []
    single_result = None
    for _ in range(args.repeats):
        t0 = time.perf_counter()
        single_result = run_one(args.w1, args.i3_ua, vp, vx, A, B, C)
        single_times.append(time.perf_counter() - t0)

    # Deterministic representative batch spanning the declared independent domain.
    n = args.batch_points
    w1_values = np.linspace(1.0, 100.0, n, dtype=np.float32)
    i3_values = np.linspace(10.0, 100.0, n, dtype=np.float32)

    batch_times = []
    batch_results = None
    for _ in range(args.repeats):
        t0 = time.perf_counter()
        batch_results = run_batch(w1_values, i3_values, vp, vx, A, B, C)
        batch_times.append(time.perf_counter() - t0)

    single_ms = 1000.0 * float(np.median(single_times))
    batch_s = float(np.median(batch_times))
    per_point_ms = 1000.0 * batch_s / n
    throughput = n / batch_s

    joined_counts = [r[3] for r in batch_results]

    print("===== PURE COMPONENT-MLP HIERARCHICAL RUNTIME =====")
    print(f"model load time                : {load_s*1000.0:.3f} ms")
    print(f"interface evaluations / point  : {len(vp)} + {len(vp)*len(vx)} + {len(vx)} = {len(vp)+len(vp)*len(vx)+len(vx)}")
    print(f"single point W1/I3             : {args.w1:.6g} um / {args.i3_ua:.6g} uA")
    print(f"single masks A/B/C/join        : {single_result[0]}/{single_result[1]}/{single_result[2]}/{single_result[3]}")
    print(f"single-point median runtime    : {single_ms:.3f} ms")
    print(f"batch independent points       : {n}")
    print(f"batch median runtime           : {batch_s:.6f} s")
    print(f"average runtime / point        : {per_point_ms:.3f} ms")
    print(f"throughput                     : {throughput:.1f} design points/s")
    print(f"batch points with >=1 join     : {sum(x > 0 for x in joined_counts)}/{n}")
    print(f"batch joined-cell min/max      : {min(joined_counts)}/{max(joined_counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Train one small PyTorch binary feasibility classifier from a component CSV.

The saved checkpoint contains:
  - feature_names
  - normalization mean/std
  - MLP architecture
  - state_dict
  - selected probability threshold

Threshold selection deliberately favors recall of valid cells.
"""
from __future__ import annotations

import argparse
import csv
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


def load_csv(path, features):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    X = np.asarray(
        [[float(r[c]) for c in features] for r in rows],
        dtype=np.float32,
    )
    y = np.asarray([int(r["valid"]) for r in rows], dtype=np.float32)
    return X, y


def stratified_split(y, val_fraction, seed):
    rng = np.random.default_rng(seed)
    train_idx = []
    val_idx = []
    for label in (0, 1):
        idx = np.where(y == label)[0]
        rng.shuffle(idx)
        nv = max(1, int(round(len(idx) * val_fraction))) if len(idx) > 1 else 0
        val_idx.extend(idx[:nv].tolist())
        train_idx.extend(idx[nv:].tolist())
    rng.shuffle(train_idx)
    rng.shuffle(val_idx)
    return np.asarray(train_idx), np.asarray(val_idx)


def confusion(y, pred):
    y = y.astype(int)
    pred = pred.astype(int)
    tp = int(np.sum((y == 1) & (pred == 1)))
    tn = int(np.sum((y == 0) & (pred == 0)))
    fp = int(np.sum((y == 0) & (pred == 1)))
    fn = int(np.sum((y == 1) & (pred == 0)))
    return tp, tn, fp, fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--features", required=True, nargs="+")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--hidden", nargs="+", type=int, default=[64, 64])
    ap.add_argument("--epochs", type=int, default=500)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-fraction", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    X, y = load_csv(args.dataset, args.features)
    if np.sum(y == 1) == 0:
        raise RuntimeError("dataset contains zero valid samples")
    if np.sum(y == 0) == 0:
        raise RuntimeError("dataset contains zero invalid samples")

    tr, va = stratified_split(y, args.val_fraction, args.seed)

    mean = X[tr].mean(axis=0)
    std = X[tr].std(axis=0)
    std[std < 1e-12] = 1.0

    Xn = (X - mean) / std

    xtr = torch.tensor(Xn[tr], dtype=torch.float32)
    ytr = torch.tensor(y[tr], dtype=torch.float32)
    xva = torch.tensor(Xn[va], dtype=torch.float32)
    yva = y[va]

    pos = float(np.sum(y[tr] == 1))
    neg = float(np.sum(y[tr] == 0))
    pos_weight = torch.tensor([neg / max(pos, 1.0)], dtype=torch.float32)

    model = MLP(len(args.features), args.hidden)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    best_state = None
    best_loss = float("inf")

    for epoch in range(args.epochs):
        model.train()
        opt.zero_grad()
        logits = model(xtr)
        loss = loss_fn(logits, ytr)
        loss.backward()
        opt.step()

        if epoch % 10 == 0 or epoch == args.epochs - 1:
            model.eval()
            with torch.no_grad():
                vloss = nn.functional.binary_cross_entropy_with_logits(
                    model(xva),
                    torch.tensor(yva, dtype=torch.float32),
                    pos_weight=pos_weight,
                ).item()
            if vloss < best_loss:
                best_loss = vloss
                best_state = {
                    k: v.detach().cpu().clone()
                    for k, v in model.state_dict().items()
                }

    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        pva = torch.sigmoid(model(xva)).numpy()

    # Favor recall: choose the highest threshold that still gives at least
    # 98% validation recall when possible.  If impossible, maximize recall
    # then precision.
    candidates = np.linspace(0.05, 0.95, 181)
    scored = []
    for th in candidates:
        pred = (pva >= th).astype(int)
        tp, tn, fp, fn = confusion(yva, pred)
        recall = tp / max(tp + fn, 1)
        precision = tp / max(tp + fp, 1)
        scored.append((th, recall, precision, tp, tn, fp, fn))

    feasible = [s for s in scored if s[1] >= 0.98]
    if feasible:
        chosen = max(feasible, key=lambda s: (s[0], s[2]))
    else:
        chosen = max(scored, key=lambda s: (s[1], s[2], s[0]))

    th, recall, precision, tp, tn, fp, fn = chosen

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "schema_version": 1,
            "kind": "binary_feasibility_classifier",
            "feature_names": list(args.features),
            "mean": mean.astype(np.float32),
            "std": std.astype(np.float32),
            "hidden": list(args.hidden),
            "state_dict": best_state,
            "threshold": float(th),
        },
        args.output,
    )

    print("===== COMPONENT FEASIBILITY MLP =====")
    print("dataset       :", args.dataset)
    print("features      :", args.features)
    print("rows          :", len(y))
    print("train / val   :", len(tr), "/", len(va))
    print("valid total   :", int(np.sum(y == 1)))
    print("invalid total :", int(np.sum(y == 0)))
    print("threshold     :", f"{th:.3f}")
    print("val recall    :", f"{recall:.4f}")
    print("val precision :", f"{precision:.4f}")
    print("val TP/TN/FP/FN:", tp, tn, fp, fn)
    print("output        :", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

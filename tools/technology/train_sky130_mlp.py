#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from openams.technology.ml_surrogate.dataset import deterministic_split, load_characterization_csv
from openams.technology.ml_surrogate.metrics import regression_metrics
from openams.technology.ml_surrogate.model import MosMlpConfig
from openams.technology.ml_surrogate.trainer import TrainingConfig, save_checkpoint, train_model


def _domain(dataset):
    f = dataset.features
    return {
        "width_um": [float(np.exp(f[:, 0]).min()), float(np.exp(f[:, 0]).max())],
        "length_um": [float(np.exp(f[:, 1]).min()), float(np.exp(f[:, 1]).max())],
        "vgs_abs_v": [float(f[:, 2].min()), float(f[:, 2].max())],
        "vds_abs_v": [float(f[:, 3].min()), float(f[:, 3].max())],
        "vbs_abs_v": [float(f[:, 4].min()), float(f[:, 4].max())],
    }


def _predict(result, features):
    scaled = result.feature_scaler.transform(features)
    with torch.no_grad():
        pred_scaled = result.model(torch.tensor(scaled, dtype=torch.float32)).numpy()
    return result.target_scaler.inverse_transform(pred_scaled)


def main() -> None:
    p = argparse.ArgumentParser(description="Train standalone SKY130 NMOS/PMOS MLP surrogates")
    p.add_argument("--table", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--epochs", type=int, default=500)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--learning-rate", type=float, default=1e-3)
    p.add_argument("--patience", type=int, default=60)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--hidden-dims", default="128,128,128,64")
    args = p.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    hidden = tuple(int(x) for x in args.hidden_dims.split(",") if x.strip())
    summary = {"table": str(Path(args.table).resolve()), "models": {}}
    for polarity in ("nmos", "pmos"):
        dataset = load_characterization_csv(args.table, polarity=polarity)
        split = deterministic_split(dataset, seed=args.seed)
        result = train_model(split, model_config=MosMlpConfig(hidden_dims=hidden),
            training_config=TrainingConfig(epochs=args.epochs, batch_size=args.batch_size,
                learning_rate=args.learning_rate, patience=args.patience, seed=args.seed))
        prediction = _predict(result, split.test.features)
        metrics = regression_metrics(split.test.targets, prediction)
        checkpoint = out / f"sky130_{polarity}_mlp.pt"
        save_checkpoint(checkpoint, result=result, polarity=polarity, domain=_domain(dataset),
                        metadata={**dataset.metadata, "row_count": len(dataset),
                                  "train_rows": len(split.train), "validation_rows": len(split.validation),
                                  "test_rows": len(split.test), "seed": args.seed})
        summary["models"][polarity] = {
            "checkpoint": str(checkpoint), "rows": len(dataset), "train_rows": len(split.train),
            "validation_rows": len(split.validation), "test_rows": len(split.test),
            "best_epoch": result.best_epoch, "best_validation_loss": result.best_validation_loss,
            "metrics": metrics,
        }
        print(f"[{polarity}] rows={len(dataset)} best_epoch={result.best_epoch} "
              f"val_loss={result.best_validation_loss:.6g} "
              f"Id_p95_rel={metrics['id_abs_a']['p95_relative_error']:.4%}")
    (out / "training_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[PASS] wrote {out / 'training_summary.json'}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from .dataset import MosDatasetSplit
from .model import MosMlp, MosMlpConfig
from .scaling import Standardizer


@dataclass(frozen=True)
class TrainingConfig:
    epochs: int = 500
    batch_size: int = 128
    learning_rate: float = 1e-3
    weight_decay: float = 1e-6
    patience: int = 50
    seed: int = 7
    device: str = "cpu"


@dataclass
class TrainingResult:
    model: MosMlp
    feature_scaler: Standardizer
    target_scaler: Standardizer
    history: list[dict[str, float]]
    best_epoch: int
    best_validation_loss: float


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def train_model(split: MosDatasetSplit, *, model_config: MosMlpConfig = MosMlpConfig(),
                training_config: TrainingConfig = TrainingConfig()) -> TrainingResult:
    _seed_everything(training_config.seed)
    feature_scaler = Standardizer.fit(split.train.features)
    target_scaler = Standardizer.fit(split.train.targets)
    x_train = torch.tensor(feature_scaler.transform(split.train.features), dtype=torch.float32)
    y_train = torch.tensor(target_scaler.transform(split.train.targets), dtype=torch.float32)
    x_val = torch.tensor(feature_scaler.transform(split.validation.features), dtype=torch.float32)
    y_val = torch.tensor(target_scaler.transform(split.validation.targets), dtype=torch.float32)
    generator = torch.Generator().manual_seed(training_config.seed)
    loader = DataLoader(TensorDataset(x_train, y_train), batch_size=training_config.batch_size,
                        shuffle=True, generator=generator)
    device = torch.device(training_config.device)
    model = MosMlp(model_config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=training_config.learning_rate,
                                  weight_decay=training_config.weight_decay)
    loss_fn = torch.nn.MSELoss()
    best_state = copy.deepcopy(model.state_dict())
    best_loss, best_epoch, stale = float("inf"), 0, 0
    history: list[dict[str, float]] = []
    for epoch in range(1, training_config.epochs + 1):
        model.train()
        total, count = 0.0, 0
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(xb), yb)
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * len(xb)
            count += len(xb)
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(x_val.to(device)), y_val.to(device)).cpu())
        train_loss = total / max(count, 1)
        history.append({"epoch": float(epoch), "train_loss": train_loss, "validation_loss": val_loss})
        if val_loss < best_loss - 1e-9:
            best_loss, best_epoch, stale = val_loss, epoch, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            stale += 1
        if stale >= training_config.patience:
            break
    model.load_state_dict(best_state)
    model.eval()
    return TrainingResult(model, feature_scaler, target_scaler, history, best_epoch, best_loss)


def save_checkpoint(path: str | Path, *, result: TrainingResult, polarity: str,
                    domain: dict[str, list[float]], metadata: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"format_version": 1, "polarity": polarity,
                "model_config": result.model.config.to_dict(),
                "model_state": result.model.state_dict(),
                "feature_scaler": result.feature_scaler.state_dict(),
                "target_scaler": result.target_scaler.state_dict(),
                "domain": domain, "metadata": metadata,
                "training": {"best_epoch": result.best_epoch,
                             "best_validation_loss": result.best_validation_loss,
                             "history": result.history}}, path)

from pathlib import Path
import numpy as np
import torch
from openams.technology.ml_surrogate.dataset import MosDataset, MosDatasetSplit
from openams.technology.ml_surrogate.model import MosMlpConfig
from openams.technology.ml_surrogate.trainer import TrainingConfig, train_model


def _dataset(n=48):
    rng = np.random.default_rng(2)
    x = rng.normal(size=(n, 5))
    y = np.column_stack((x[:,0]+x[:,2], x[:,0]-x[:,2], x[:,1]+0.2*x[:,3], x[:,3], x[:,4]))
    return MosDataset("nmos", x, y, np.ones(n, bool), tuple(str(i) for i in range(n)), {})

def test_tiny_dataset_can_overfit():
    ds = _dataset()
    split = MosDatasetSplit(ds, ds, ds)
    result = train_model(split, model_config=MosMlpConfig(hidden_dims=(32,32)),
        training_config=TrainingConfig(epochs=500, batch_size=48, learning_rate=5e-3, patience=100, seed=1))
    x = torch.tensor(result.feature_scaler.transform(ds.features), dtype=torch.float32)
    with torch.no_grad():
        pred = result.target_scaler.inverse_transform(result.model(x).numpy())
    assert np.mean((pred-ds.targets)**2) < 2e-3

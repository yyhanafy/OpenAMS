from pathlib import Path
import numpy as np
from openams.technology.ml_surrogate.dataset import deterministic_split, load_characterization_csv

TABLE = Path("technology/sky130_tt_27c_inverse_smoke.csv")

def test_load_and_transform_dataset():
    ds = load_characterization_csv(TABLE, polarity="nmos")
    assert len(ds) == 1512
    assert ds.features.shape == (1512, 5)
    assert ds.targets.shape == (1512, 5)
    assert np.isfinite(ds.features).all()
    assert np.isfinite(ds.targets).all()

def test_split_is_deterministic_and_disjoint():
    ds = load_characterization_csv(TABLE, polarity="pmos")
    a, b = deterministic_split(ds, seed=7), deterministic_split(ds, seed=7)
    assert a.test.row_keys == b.test.row_keys
    assert set(a.train.row_keys).isdisjoint(a.validation.row_keys)
    assert set(a.train.row_keys).isdisjoint(a.test.row_keys)
    assert len(a.train) + len(a.validation) + len(a.test) == len(ds)

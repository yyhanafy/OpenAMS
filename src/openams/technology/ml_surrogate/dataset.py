from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

FEATURE_NAMES = ("log_width_um", "log_length_um", "vgs_abs_v", "vds_abs_v", "vbs_abs_v")
TARGET_NAMES = ("log_id_abs_a", "log_gm_s", "log_gds_s", "vdsat_abs_v", "vth_abs_v")
REQUIRED_COLUMNS = {
    "polarity", "model", "corner", "temperature_c", "length_um", "width_um",
    "vgs_abs_v", "vds_abs_v", "vbs_abs_v", "id_abs_a", "vdsat_abs_v",
    "vth_abs_v", "gm_s", "gds_s", "saturated",
}
_LOG_FLOOR = 1e-30


@dataclass(frozen=True)
class MosDataset:
    polarity: str
    features: np.ndarray
    targets: np.ndarray
    saturated: np.ndarray
    row_keys: tuple[str, ...]
    metadata: dict[str, object]

    def __len__(self) -> int:
        return int(self.features.shape[0])


@dataclass(frozen=True)
class MosDatasetSplit:
    train: MosDataset
    validation: MosDataset
    test: MosDataset


def _float(row: dict[str, str], name: str) -> float:
    value = float(row[name])
    if not np.isfinite(value):
        raise ValueError(f"non-finite {name}: {row[name]!r}")
    return value


def _row_key(row: dict[str, str]) -> str:
    names = ("polarity", "model", "corner", "temperature_c", "length_um", "width_um",
             "vgs_abs_v", "vds_abs_v", "vbs_abs_v")
    return "|".join(str(row[name]).strip() for name in names)


def load_characterization_csv(path: str | Path, *, polarity: str) -> MosDataset:
    polarity = polarity.lower()
    if polarity not in {"nmos", "pmos"}:
        raise ValueError("polarity must be 'nmos' or 'pmos'")
    path = Path(path)
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing required columns: {sorted(missing)}")
        rows = [r for r in reader if r["polarity"].strip().lower() == polarity]
    if not rows:
        raise ValueError(f"no {polarity} rows in {path}")

    seen: set[str] = set()
    features, targets, saturated, keys = [], [], [], []
    models, corners, temperatures = set(), set(), set()
    for row in rows:
        key = _row_key(row)
        if key in seen:
            continue
        seen.add(key)
        w, l = _float(row, "width_um"), _float(row, "length_um")
        if w <= 0 or l <= 0:
            raise ValueError(f"width and length must be positive: {key}")
        id_a = max(abs(_float(row, "id_abs_a")), _LOG_FLOOR)
        gm = max(abs(_float(row, "gm_s")), _LOG_FLOOR)
        gds = max(abs(_float(row, "gds_s")), _LOG_FLOOR)
        features.append([np.log(w), np.log(l), _float(row, "vgs_abs_v"),
                         _float(row, "vds_abs_v"), _float(row, "vbs_abs_v")])
        targets.append([np.log(id_a), np.log(gm), np.log(gds),
                        _float(row, "vdsat_abs_v"), _float(row, "vth_abs_v")])
        saturated.append(bool(int(float(row["saturated"]))))
        keys.append(key)
        models.add(row["model"].strip())
        corners.add(row["corner"].strip())
        temperatures.add(_float(row, "temperature_c"))
    return MosDataset(
        polarity=polarity,
        features=np.asarray(features, dtype=np.float64),
        targets=np.asarray(targets, dtype=np.float64),
        saturated=np.asarray(saturated, dtype=bool),
        row_keys=tuple(keys),
        metadata={"source": str(path), "models": sorted(models), "corners": sorted(corners),
                  "temperatures_c": sorted(temperatures), "feature_names": FEATURE_NAMES,
                  "target_names": TARGET_NAMES},
    )


def _subset(dataset: MosDataset, indices: Iterable[int]) -> MosDataset:
    idx = np.asarray(list(indices), dtype=np.int64)
    return MosDataset(dataset.polarity, dataset.features[idx], dataset.targets[idx],
                      dataset.saturated[idx], tuple(dataset.row_keys[i] for i in idx), dataset.metadata)


def deterministic_split(dataset: MosDataset, *, validation_fraction: float = 0.15,
                        test_fraction: float = 0.15, seed: int = 7) -> MosDatasetSplit:
    if validation_fraction < 0 or test_fraction < 0 or validation_fraction + test_fraction >= 1:
        raise ValueError("validation_fraction and test_fraction must be non-negative and sum to < 1")
    train, validation, test = [], [], []
    for i, key in enumerate(dataset.row_keys):
        digest = hashlib.sha256(f"{seed}|{key}".encode()).digest()
        u = int.from_bytes(digest[:8], "big") / 2**64
        if u < test_fraction:
            test.append(i)
        elif u < test_fraction + validation_fraction:
            validation.append(i)
        else:
            train.append(i)
    if not train or not validation or not test:
        raise ValueError("dataset is too small for requested deterministic split")
    return MosDatasetSplit(_subset(dataset, train), _subset(dataset, validation), _subset(dataset, test))

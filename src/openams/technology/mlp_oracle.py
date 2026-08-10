from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import torch

from openams.technology.ml_surrogate.predictor import MosMlpBundle


def _scale_forward(values: np.ndarray, scaler) -> np.ndarray:
    mean = np.asarray(scaler.mean, dtype=np.float64)
    scale = np.asarray(scaler.scale, dtype=np.float64)
    return (values - mean) / scale


def _scale_inverse(values: np.ndarray, scaler) -> np.ndarray:
    mean = np.asarray(scaler.mean, dtype=np.float64)
    scale = np.asarray(scaler.scale, dtype=np.float64)
    return values * scale + mean


@dataclass
class MlpOracle:
    """Topology-independent batched MOS MLP evaluator.

    The oracle owns no circuit equations.  It only evaluates a characterized
    MOS device model and reports whether requested points lie inside the model
    domain.
    """

    bundle: MosMlpBundle
    length_um: float = 0.5
    calls: int = 0
    points: int = 0

    @classmethod
    def load(
        cls,
        checkpoints: Mapping[str, str | Path],
        *,
        length_um: float = 0.5,
    ) -> "MlpOracle":
        paths = {name: Path(path) for name, path in checkpoints.items()}
        return cls(MosMlpBundle.load(paths), length_um=float(length_um))

    def width_domain(self, polarity: str) -> tuple[float, float]:
        lo, hi = self.bundle.models[polarity].domain["width_um"]
        return float(lo), float(hi)

    def inside_domain(
        self,
        polarity: str,
        width_um,
        vgs_v,
        vds_v,
        vbs_v,
    ) -> np.ndarray:
        width, vgs, vds, vbs = np.broadcast_arrays(
            np.asarray(width_um, dtype=np.float64),
            np.asarray(vgs_v, dtype=np.float64),
            np.asarray(vds_v, dtype=np.float64),
            np.asarray(vbs_v, dtype=np.float64),
        )
        domain = self.bundle.models[polarity].domain
        return (
            (width >= float(domain["width_um"][0]))
            & (width <= float(domain["width_um"][1]))
            & (vgs >= float(domain["vgs_abs_v"][0]))
            & (vgs <= float(domain["vgs_abs_v"][1]))
            & (vds >= float(domain["vds_abs_v"][0]))
            & (vds <= float(domain["vds_abs_v"][1]))
            & (vbs >= float(domain["vbs_abs_v"][0]))
            & (vbs <= float(domain["vbs_abs_v"][1]))
        )

    def predict(
        self,
        polarity: str,
        width_um,
        vgs_v,
        vds_v,
        vbs_v,
    ) -> dict[str, np.ndarray]:
        width, vgs, vds, vbs = np.broadcast_arrays(
            np.asarray(width_um, dtype=np.float64),
            np.asarray(vgs_v, dtype=np.float64),
            np.asarray(vds_v, dtype=np.float64),
            np.asarray(vbs_v, dtype=np.float64),
        )
        shape = width.shape
        loaded = self.bundle.models[polarity]
        feature_names = list(loaded.metadata["feature_names"])
        target_names = list(loaded.metadata["target_names"])

        columns = {
            "log_width_um": np.log(width.ravel()),
            "log_length_um": np.full(
                width.size, np.log(self.length_um), dtype=np.float64
            ),
            "vgs_abs_v": vgs.ravel(),
            "vds_abs_v": vds.ravel(),
            "vbs_abs_v": vbs.ravel(),
        }
        x = np.column_stack([columns[name] for name in feature_names])
        xn = _scale_forward(x, loaded.feature_scaler).astype(np.float32)

        with torch.inference_mode():
            yn = loaded.model(torch.from_numpy(xn)).cpu().numpy()
        decoded = _scale_inverse(yn, loaded.target_scaler)

        result: dict[str, np.ndarray] = {}
        for index, name in enumerate(target_names):
            values = decoded[:, index]
            if name.startswith("log_"):
                values = np.exp(values)
                name = name[4:]
            result[name] = values.reshape(shape)

        self.calls += 1
        self.points += width.size
        return result

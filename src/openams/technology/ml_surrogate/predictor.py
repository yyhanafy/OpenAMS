from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import torch
from scipy.optimize import brentq

from .model import MosMlp, MosMlpConfig
from .scaling import Standardizer


@dataclass(frozen=True)
class MosPrediction:
    id_abs_a: float
    gm_s: float
    gds_s: float
    vdsat_abs_v: float
    vth_abs_v: float
    saturated: bool
    saturation_margin_v: float
    in_domain: bool


@dataclass(frozen=True)
class MosSolveResult:
    solve_for: str
    value: float
    target_current_a: float
    achieved_current_a: float
    residual_a: float
    bracket: tuple[float, float]
    saturated: bool
    method: str


class _LoadedModel:
    def __init__(self, checkpoint: dict[str, object]):
        self.polarity = str(checkpoint["polarity"])
        self.model = MosMlp(MosMlpConfig.from_dict(checkpoint["model_config"]))
        self.model.load_state_dict(checkpoint["model_state"])
        self.model.eval()
        self.feature_scaler = Standardizer.from_state_dict(checkpoint["feature_scaler"])
        self.target_scaler = Standardizer.from_state_dict(checkpoint["target_scaler"])
        self.domain = checkpoint["domain"]
        self.metadata = checkpoint.get("metadata", {})

    def _features(self, width_um: float, length_um: float, vgs_abs_v: float,
                  vds_abs_v: float, vbs_abs_v: float) -> np.ndarray:
        if width_um <= 0 or length_um <= 0:
            raise ValueError("width_um and length_um must be positive")
        return np.asarray([[np.log(width_um), np.log(length_um), vgs_abs_v, vds_abs_v, vbs_abs_v]])

    def in_domain(self, *, width_um: float, length_um: float, vgs_abs_v: float,
                  vds_abs_v: float, vbs_abs_v: float) -> bool:
        values = {"width_um": width_um, "length_um": length_um, "vgs_abs_v": vgs_abs_v,
                  "vds_abs_v": vds_abs_v, "vbs_abs_v": vbs_abs_v}
        return all(float(self.domain[k][0]) <= v <= float(self.domain[k][1]) for k, v in values.items())

    def predict(self, *, width_um: float, length_um: float, vgs_abs_v: float,
                vds_abs_v: float, vbs_abs_v: float, saturation_margin_v: float = 0.0,
                allow_extrapolation: bool = False) -> MosPrediction:
        inside = self.in_domain(width_um=width_um, length_um=length_um, vgs_abs_v=vgs_abs_v,
                                vds_abs_v=vds_abs_v, vbs_abs_v=vbs_abs_v)
        if not inside and not allow_extrapolation:
            raise ValueError("query lies outside the characterized model domain")
        x = self.feature_scaler.transform(self._features(width_um, length_um, vgs_abs_v, vds_abs_v, vbs_abs_v))
        with torch.no_grad():
            y_scaled = self.model(torch.tensor(x, dtype=torch.float32)).numpy()
        y = self.target_scaler.inverse_transform(y_scaled)[0]
        id_a, gm, gds = (float(np.exp(y[i])) for i in range(3))
        vdsat, vth = float(y[3]), float(y[4])
        margin = float(vds_abs_v - vdsat)
        return MosPrediction(id_a, gm, gds, vdsat, vth, margin >= saturation_margin_v,
                             margin, inside)


class MosMlpBundle:
    def __init__(self, models: dict[str, _LoadedModel]):
        self.models = models

    @classmethod
    def load(cls, checkpoints: dict[str, str | Path]) -> "MosMlpBundle":
        loaded = {}
        for polarity, path in checkpoints.items():
            try:
                state = torch.load(Path(path), map_location="cpu", weights_only=False)
            except TypeError:
                state = torch.load(Path(path), map_location="cpu")
            loaded[polarity.lower()] = _LoadedModel(state)
        return cls(loaded)

    def predict(self, *, polarity: str, width_um: float, length_um: float,
                vgs_abs_v: float, vds_abs_v: float, vbs_abs_v: float,
                saturation_margin_v: float = 0.0, allow_extrapolation: bool = False) -> MosPrediction:
        return self.models[polarity.lower()].predict(width_um=width_um, length_um=length_um,
            vgs_abs_v=vgs_abs_v, vds_abs_v=vds_abs_v, vbs_abs_v=vbs_abs_v,
            saturation_margin_v=saturation_margin_v, allow_extrapolation=allow_extrapolation)

    def _solve(self, *, polarity: str, solve_for: str, target_current_a: float,
               lower: float, upper: float, prediction_for: Callable[[float], MosPrediction],
               require_saturation: bool, xtol: float) -> MosSolveResult:
        if target_current_a <= 0:
            raise ValueError("target_current_a must be positive")
        samples = np.linspace(lower, upper, 129)
        predictions = [prediction_for(float(v)) for v in samples]
        currents = np.asarray([p.id_abs_a for p in predictions])
        if require_saturation:
            valid = np.asarray([p.saturated for p in predictions])
        else:
            valid = np.ones_like(currents, dtype=bool)
        candidates = []
        for i in range(len(samples) - 1):
            if not (valid[i] and valid[i + 1]):
                continue
            a, b = currents[i] - target_current_a, currents[i + 1] - target_current_a
            if a == 0 or a * b <= 0:
                candidates.append((float(samples[i]), float(samples[i + 1])))
        if not candidates:
            valid_currents = currents[valid]
            if valid_currents.size == 0:
                raise ValueError("no valid saturated points in requested solve interval")
            raise ValueError(f"target current is not bracketed; achievable range is "
                             f"[{valid_currents.min():.6g}, {valid_currents.max():.6g}] A")
        bracket = candidates[0]
        root = brentq(lambda value: prediction_for(float(value)).id_abs_a - target_current_a,
                      bracket[0], bracket[1], xtol=xtol, rtol=1e-10)
        prediction = prediction_for(float(root))
        if require_saturation and not prediction.saturated:
            raise ValueError("root is not saturated")
        return MosSolveResult(solve_for, float(root), target_current_a, prediction.id_abs_a,
                              prediction.id_abs_a-target_current_a, bracket, prediction.saturated,
                              "mlp_brentq")

    def solve_width(self, *, polarity: str, target_current_a: float, length_um: float,
                    vgs_abs_v: float, vds_abs_v: float, vbs_abs_v: float,
                    minimum_width_um: float | None = None, maximum_width_um: float | None = None,
                    require_saturation: bool = False, saturation_margin_v: float = 0.0,
                    xtol: float = 1e-8) -> MosSolveResult:
        model = self.models[polarity.lower()]
        lower = float(minimum_width_um if minimum_width_um is not None else model.domain["width_um"][0])
        upper = float(maximum_width_um if maximum_width_um is not None else model.domain["width_um"][1])
        return self._solve(polarity=polarity, solve_for="width", target_current_a=target_current_a,
            lower=lower, upper=upper, require_saturation=require_saturation, xtol=xtol,
            prediction_for=lambda width: model.predict(width_um=width, length_um=length_um,
                vgs_abs_v=vgs_abs_v, vds_abs_v=vds_abs_v, vbs_abs_v=vbs_abs_v,
                saturation_margin_v=saturation_margin_v))

    def solve_vgs(self, *, polarity: str, target_current_a: float, width_um: float,
                  length_um: float, vds_abs_v: float, vbs_abs_v: float,
                  minimum_vgs_abs_v: float | None = None, maximum_vgs_abs_v: float | None = None,
                  require_saturation: bool = False, saturation_margin_v: float = 0.0,
                  xtol: float = 1e-8) -> MosSolveResult:
        model = self.models[polarity.lower()]
        lower = float(minimum_vgs_abs_v if minimum_vgs_abs_v is not None else model.domain["vgs_abs_v"][0])
        upper = float(maximum_vgs_abs_v if maximum_vgs_abs_v is not None else model.domain["vgs_abs_v"][1])
        return self._solve(polarity=polarity, solve_for="vgs", target_current_a=target_current_a,
            lower=lower, upper=upper, require_saturation=require_saturation, xtol=xtol,
            prediction_for=lambda vgs: model.predict(width_um=width_um, length_um=length_um,
                vgs_abs_v=vgs, vds_abs_v=vds_abs_v, vbs_abs_v=vbs_abs_v,
                saturation_margin_v=saturation_margin_v))

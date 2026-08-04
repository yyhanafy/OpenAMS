"""MLP device-provider backend for the topology-generic Step-5 scan.

This provider uses the same ``MlpContinuousTechnologyOracle`` as the frozen
10,000-point two-stage scan.  It converts a generic DeviceRequest into one or
more technology realizations and exposes the oracle's exact query counter.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from openams.synthesis.generic_complete_step5 import (
    DeviceRealization,
    DeviceRequest,
    GenericStep5Error,
    _minimum_nf,
)
from openams.technology.ml_continuous_oracle import MlpContinuousTechnologyOracle


def _value(point: Any, name: str, default: Any = None) -> Any:
    if isinstance(point, Mapping):
        return point.get(name, default)
    return getattr(point, name, default)


class MlpDeviceProvider:
    """Continuous MLP provider with deterministic voltage-grid inversion.

    Known VGS/VDS coordinates are evaluated directly.  Unknown coordinates are
    explored on deterministic grids.  For dependent widths, the MLP is first
    queried at 1 um, then current-density scaling proposes a width, and the MLP
    is queried again at that actual width for verification.
    """

    name = "continuous_dense_mlp"

    def __init__(
        self,
        *,
        nmos_checkpoint: Path,
        pmos_checkpoint: Path,
        adaptive_output: Path,
        vgs_min_v: float = 0.5,
        vgs_max_v: float = 1.2,
        vgs_count: int = 8,
        vds_min_v: float = 0.15,
        vds_max_v: float = 1.5,
        vds_count: int = 10,
    ) -> None:
        self.oracle = MlpContinuousTechnologyOracle(
            {"nmos": nmos_checkpoint, "pmos": pmos_checkpoint},
            adaptive_output,
        )
        self.vgs_grid = np.linspace(vgs_min_v, vgs_max_v, vgs_count)
        self.vds_grid = np.linspace(vds_min_v, vds_max_v, vds_count)

    @property
    def query_count(self) -> int:
        return int(self.oracle.query_count)

    def flush(self) -> None:
        flush = getattr(self.oracle, "flush_cache", None)
        if callable(flush):
            flush()

    def _predict(
        self,
        request: DeviceRequest,
        *,
        width_um: float,
        vgs_v: float,
        vds_v: float,
    ) -> Any:
        return self.oracle.predict(
            polarity=request.polarity,
            width_um=float(width_um),
            length_um=float(request.length_um),
            vgs_abs_v=float(vgs_v),
            vds_abs_v=float(vds_v),
            vbs_abs_v=float(request.known_vbs_v or 0.0),
            allow_extrapolation=False,
            persist=False,
        )

    def candidates(
        self,
        request: DeviceRequest,
        *,
        current_relative_tolerance: float,
        current_absolute_tolerance_a: float,
        voltage_tolerance_v: float,
        width_policy: Mapping[str, float | int],
        limit: int,
    ) -> Sequence[DeviceRealization]:
        allowed_current_error = max(
            current_absolute_tolerance_a,
            current_relative_tolerance * max(abs(request.target_current_a), 1e-30),
        )
        vgs_values = (
            [float(request.known_vgs_v)]
            if request.known_vgs_v is not None
            else [float(value) for value in self.vgs_grid]
        )
        vds_values = (
            [float(request.known_vds_v)]
            if request.known_vds_v is not None
            else [float(value) for value in self.vds_grid]
        )
        scored: list[tuple[tuple[float, float, float, float], DeviceRealization]] = []

        for vgs_v in vgs_values:
            for vds_v in vds_values:
                if vgs_v <= 0.0 or vds_v <= 0.0:
                    continue
                try:
                    if request.fixed_width_um is None:
                        reference = self._predict(
                            request,
                            width_um=1.0,
                            vgs_v=vgs_v,
                            vds_v=vds_v,
                        )
                        reference_current = float(_value(reference, "id_abs_a"))
                        if reference_current <= 0.0:
                            continue
                        width_um = request.target_current_a / reference_current
                    else:
                        width_um = float(request.fixed_width_um)

                    nf = _minimum_nf(width_um, width_policy)
                    if nf is None:
                        continue

                    point = self._predict(
                        request,
                        width_um=width_um,
                        vgs_v=vgs_v,
                        vds_v=vds_v,
                    )
                except (ValueError, RuntimeError, KeyError, FloatingPointError):
                    continue

                predicted_current = float(_value(point, "id_abs_a"))
                current_error = abs(predicted_current - request.target_current_a)
                if current_error > allowed_current_error:
                    continue
                saturated = bool(_value(point, "saturated", False))
                in_domain = bool(_value(point, "in_domain", True))
                if request.require_saturation and not saturated:
                    continue
                if not in_domain:
                    continue

                point_vgs = float(_value(point, "vgs_abs_v", vgs_v))
                point_vds = float(_value(point, "vds_abs_v", vds_v))
                point_vbs = float(_value(point, "vbs_abs_v", request.known_vbs_v or 0.0))
                voltage_errors = [
                    abs(point_vgs - request.known_vgs_v) if request.known_vgs_v is not None else 0.0,
                    abs(point_vds - request.known_vds_v) if request.known_vds_v is not None else 0.0,
                    abs(point_vbs - request.known_vbs_v) if request.known_vbs_v is not None else 0.0,
                ]
                max_voltage_error = max(voltage_errors)
                realization = DeviceRealization(
                    width_um=width_um,
                    nf=nf,
                    finger_width_um=width_um / nf,
                    predicted_current_a=predicted_current,
                    vgs_v=point_vgs,
                    vds_v=point_vds,
                    vbs_v=point_vbs,
                    vdsat_v=(
                        float(_value(point, "vdsat_abs_v"))
                        if _value(point, "vdsat_abs_v") is not None
                        else None
                    ),
                    saturated=saturated,
                    provenance={
                        "provider": self.name,
                        "source": str(_value(point, "source", "mlp")),
                        "in_domain": in_domain,
                        "current_absolute_error_a": current_error,
                        "current_relative_error": current_error / max(abs(request.target_current_a), 1e-30),
                        "maximum_voltage_mismatch_v": max_voltage_error,
                        "gm_s": _value(point, "gm_s"),
                        "gds_s": _value(point, "gds_s"),
                        "vth_abs_v": _value(point, "vth_abs_v"),
                    },
                )
                scored.append(
                    (
                        (
                            current_error / max(abs(request.target_current_a), 1e-30),
                            max_voltage_error,
                            sum(voltage_errors),
                            width_um,
                        ),
                        realization,
                    )
                )

        scored.sort(key=lambda item: item[0])
        return [item[1] for item in scored[:limit]]

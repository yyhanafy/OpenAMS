"""MLP device-provider backend for the topology-generic Step-5 scan.

This provider uses the same ``MlpContinuousTechnologyOracle`` as the frozen
characterized circuit scan.  It converts a generic DeviceRequest into one or
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
    """Continuous MLP provider constrained by circuit terminal relationships."""

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
        vbs_min_v: float = 0.0,
        vbs_max_v: float = 0.3,
        vbs_count: int = 7,
    ) -> None:
        self.oracle = MlpContinuousTechnologyOracle(
            {"nmos": nmos_checkpoint, "pmos": pmos_checkpoint},
            adaptive_output,
        )
        self.vgs_grid = np.linspace(vgs_min_v, vgs_max_v, vgs_count)
        self.vds_grid = np.linspace(vds_min_v, vds_max_v, vds_count)
        self.vbs_grid = np.linspace(vbs_min_v, vbs_max_v, vbs_count)

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
        vbs_v: float,
    ) -> Any:
        return self.oracle.predict(
            polarity=request.polarity,
            width_um=float(width_um),
            length_um=float(request.length_um),
            vgs_abs_v=float(vgs_v),
            vds_abs_v=float(vds_v),
            vbs_abs_v=float(vbs_v),
            allow_extrapolation=False,
            persist=False,
        )

    def _voltage_points(
        self,
        request: DeviceRequest,
    ) -> Sequence[tuple[float, float, float]]:
        """Generate only circuit-consistent (VGS,VDS,VBS) coordinates."""

        vg = request.known_gate_v
        vd = request.known_drain_v
        vs = request.known_source_v
        vb = request.known_bulk_v

        points: list[tuple[float, float, float]] = []

        # Most constrained case: source is already known.
        if vs is not None:
            if request.known_vgs_v is not None:
                vgs_values = [float(request.known_vgs_v)]
            elif vg is not None:
                vgs_values = [
                    float(vg - vs if request.polarity == "nmos" else vs - vg)
                ]
            else:
                vgs_values = [float(x) for x in self.vgs_grid]

            if request.known_vbs_v is not None:
                vbs_values = [abs(float(request.known_vbs_v))]
            elif vb is not None:
                vbs_values = [abs(float(vb - vs))]
            else:
                vbs_values = [float(x) for x in self.vbs_grid]

            if request.known_vds_v is not None:
                vds_values = [float(request.known_vds_v)]
            elif vd is not None:
                vds_values = [
                    float(vd - vs if request.polarity == "nmos" else vs - vd)
                ]
            else:
                vds_values = [float(x) for x in self.vds_grid]

            for vgs in vgs_values:
                for vds in vds_values:
                    for vbs in vbs_values:
                        points.append((vgs, vds, vbs))
            return points

        # Source unknown, but gate and bulk known:
        # choose VBS, derive source, then derive VGS and possibly VDS.
        if vg is not None and vb is not None:
            for raw_vbs in self.vbs_grid:
                vbs = float(raw_vbs)

                if request.polarity == "nmos":
                    source = float(vb) + vbs
                    vgs = float(vg) - source
                    derived_vds = (
                        float(vd) - source if vd is not None else None
                    )
                else:
                    source = float(vb) - vbs
                    vgs = source - float(vg)
                    derived_vds = (
                        source - float(vd) if vd is not None else None
                    )

                if request.known_vgs_v is not None:
                    if abs(vgs - float(request.known_vgs_v)) > 1e-12:
                        continue

                if request.known_vbs_v is not None:
                    if abs(vbs - abs(float(request.known_vbs_v))) > 1e-12:
                        continue

                if request.known_vds_v is not None:
                    vds_values = [float(request.known_vds_v)]
                elif derived_vds is not None:
                    vds_values = [derived_vds]
                else:
                    vds_values = [float(x) for x in self.vds_grid]

                for vds in vds_values:
                    points.append((vgs, vds, vbs))

            return points

        # Fallback for partially unconstrained devices.
        vgs_values = (
            [float(request.known_vgs_v)]
            if request.known_vgs_v is not None
            else [float(x) for x in self.vgs_grid]
        )
        vds_values = (
            [float(request.known_vds_v)]
            if request.known_vds_v is not None
            else [float(x) for x in self.vds_grid]
        )
        vbs_values = (
            [float(request.known_vbs_v)]
            if request.known_vbs_v is not None
            else [float(x) for x in self.vbs_grid]
        )

        for vgs in vgs_values:
            for vds in vds_values:
                for vbs in vbs_values:
                    points.append((vgs, vds, vbs))

        return points

    def _solve_width(
        self,
        request: DeviceRequest,
        *,
        vgs_v: float,
        vds_v: float,
        vbs_v: float,
        width_policy: Mapping[str, float | int],
        target_current_a: float,
        max_iterations: int = 40,
    ) -> float | None:
        """Solve Id(W) = target current using the continuous MLP."""

        lo = float(width_policy["total_min_um"])
        hi = float(width_policy["total_max_um"])

        # Respect the actual MLP training domain.
        if request.polarity == "nmos":
            lo = max(lo, 1.0)
        else:
            lo = max(lo, 2.0)

        def current(width_um: float) -> float:
            point = self._predict(
                request,
                width_um=width_um,
                vgs_v=vgs_v,
                vds_v=vds_v,
                vbs_v=vbs_v,
            )
            return float(_value(point, "id_abs_a"))

        try:
            flo = current(lo) - target_current_a
            fhi = current(hi) - target_current_a
        except (ValueError, RuntimeError, KeyError, FloatingPointError):
            return None

        if abs(flo) <= 1e-15:
            return lo
        if abs(fhi) <= 1e-15:
            return hi

        # No width solution inside the allowed physical interval.
        if flo * fhi > 0.0:
            return None

        for _ in range(max_iterations):
            mid = 0.5 * (lo + hi)

            try:
                fm = current(mid) - target_current_a
            except (ValueError, RuntimeError, KeyError, FloatingPointError):
                return None

            if abs(fm) <= max(
                1e-12,
                1e-5 * abs(target_current_a),
            ):
                return mid

            if flo * fm <= 0.0:
                hi = mid
                fhi = fm
            else:
                lo = mid
                flo = fm

        return 0.5 * (lo + hi)

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
            current_relative_tolerance
            * max(abs(request.target_current_a), 1e-30),
        )

        scored: list[
            tuple[tuple[float, float, float, float], DeviceRealization]
        ] = []

        for vgs_v, vds_v, vbs_v in self._voltage_points(request):

            if vgs_v <= 0.0 or vds_v <= 0.0:
                continue

            try:
                if request.fixed_width_um is None:
                    width_um = self._solve_width(
                        request,
                        vgs_v=vgs_v,
                        vds_v=vds_v,
                        vbs_v=vbs_v,
                        width_policy=width_policy,
                        target_current_a=request.target_current_a,
                    )
                    if width_um is None:
                        continue
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
                    vbs_v=vbs_v,
                )

            except (
                ValueError,
                RuntimeError,
                KeyError,
                FloatingPointError,
            ):
                continue

            predicted_current = float(
                _value(point, "id_abs_a")
            )
            current_error = abs(
                predicted_current - request.target_current_a
            )

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
            point_vbs = float(_value(point, "vbs_abs_v", vbs_v))

            voltage_errors = [
                (
                    abs(point_vgs - request.known_vgs_v)
                    if request.known_vgs_v is not None
                    else 0.0
                ),
                (
                    abs(point_vds - request.known_vds_v)
                    if request.known_vds_v is not None
                    else 0.0
                ),
                (
                    abs(point_vbs - request.known_vbs_v)
                    if request.known_vbs_v is not None
                    else 0.0
                ),
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
                    "current_relative_error": (
                        current_error
                        / max(abs(request.target_current_a), 1e-30)
                    ),
                    "maximum_voltage_mismatch_v": max_voltage_error,
                    "gm_s": _value(point, "gm_s"),
                    "gds_s": _value(point, "gds_s"),
                    "vth_abs_v": _value(point, "vth_abs_v"),
                },
            )

            scored.append(
                (
                    (
                        current_error
                        / max(abs(request.target_current_a), 1e-30),
                        max_voltage_error,
                        sum(voltage_errors),
                        width_um,
                    ),
                    realization,
                )
            )

        scored.sort(key=lambda item: item[0])
        return [item[1] for item in scored[:limit]]


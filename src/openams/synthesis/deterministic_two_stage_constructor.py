from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from scipy.optimize import brentq

from openams.technology.ml_continuous_oracle import (
    ContinuousMosPoint,
    MlpContinuousTechnologyOracle,
)


class ConstructionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TwoStageConstructionPolicy:
    # Explicit design-intent choices; never hidden scans.
    n1_v: float = 0.60
    vbias_v: float = 0.60
    iout_min_a: float = 1e-8
    iout_max_a: float = 2e-3
    width_min_um: float = 0.42
    width_max_um: float = 100.0
    current_tolerance_a: float = 2e-8
    relation_tolerance: float = 5e-3


@dataclass(frozen=True)
class ScalarSolve:
    value: float
    point: ContinuousMosPoint
    residual_a: float


def _bracket(function: Callable[[float], float], lo: float, hi: float, samples: int = 48):
    x0, y0 = lo, function(lo)
    if y0 == 0.0:
        return lo, lo
    for index in range(1, samples + 1):
        x1 = lo + (hi - lo) * index / samples
        y1 = function(x1)
        if y1 == 0.0:
            return x1, x1
        if y0 * y1 < 0.0:
            return x0, x1
        x0, y0 = x1, y1
    raise ConstructionError(f"no scalar root bracket in [{lo}, {hi}]")


def _root(function: Callable[[float], float], lo: float, hi: float) -> float:
    a, b = _bracket(function, lo, hi)
    if a == b:
        return a
    return float(brentq(function, a, b, xtol=1e-10, rtol=1e-10, maxiter=100))


def _solve_vgs(
    oracle: MlpContinuousTechnologyOracle,
    *, polarity: str, target_current_a: float, width_um: float,
    length_um: float, vds_from_vgs: Callable[[float], float],
    vgs_min_v: float, vgs_max_v: float, tolerance_a: float,
) -> ScalarSolve:
    def residual(vgs_v: float) -> float:
        vds_v = float(vds_from_vgs(vgs_v))
        if vds_v <= 0.0:
            return -target_current_a
        return oracle.predict(
            polarity=polarity, width_um=width_um, length_um=length_um,
            vgs_abs_v=vgs_v, vds_abs_v=vds_v, vbs_abs_v=0.0,
            allow_extrapolation=False, persist=False,
        ).id_abs_a - target_current_a

    vgs_v = _root(residual, vgs_min_v, vgs_max_v)
    vds_v = float(vds_from_vgs(vgs_v))
    point = oracle.predict(
        polarity=polarity, width_um=width_um, length_um=length_um,
        vgs_abs_v=vgs_v, vds_abs_v=vds_v, vbs_abs_v=0.0,
        allow_extrapolation=False, persist=False,
    )
    error = point.id_abs_a - target_current_a
    if abs(error) > tolerance_a:
        raise ConstructionError(f"VGS residual {error} A exceeds tolerance")
    return ScalarSolve(vgs_v, point, error)


def _solve_width(
    oracle: MlpContinuousTechnologyOracle,
    *, polarity: str, target_current_a: float, length_um: float,
    vgs_abs_v: float, vds_abs_v: float, width_min_um: float,
    width_max_um: float, tolerance_a: float,
) -> ScalarSolve:
    def residual(width_um: float) -> float:
        return oracle.predict(
            polarity=polarity, width_um=width_um, length_um=length_um,
            vgs_abs_v=vgs_abs_v, vds_abs_v=vds_abs_v, vbs_abs_v=0.0,
            allow_extrapolation=False, persist=False,
        ).id_abs_a - target_current_a

    width_um = _root(residual, width_min_um, width_max_um)
    point = oracle.predict(
        polarity=polarity, width_um=width_um, length_um=length_um,
        vgs_abs_v=vgs_abs_v, vds_abs_v=vds_abs_v, vbs_abs_v=0.0,
        allow_extrapolation=False, persist=False,
    )
    error = point.id_abs_a - target_current_a
    if abs(error) > tolerance_a:
        raise ConstructionError(f"width residual {error} A exceeds tolerance")
    return ScalarSolve(width_um, point, error)


def construct_two_stage_assignment(
    oracle: MlpContinuousTechnologyOracle,
    *, i_m5_a: float, w_m1_um: float, vout_v: float,
    policy: TwoStageConstructionPolicy,
    vdd_v: float = 1.8, vss_v: float = 0.0,
    vin_cm_v: float = 0.9, length_um: float = 0.5,
) -> dict[str, Any]:
    # Exact compiler rules.
    i1_a = i2_a = i3_a = i4_a = i_m5_a / 2.0
    w2_um = w_m1_um
    n1_v = policy.n1_v
    vbias_v = policy.vbias_v

    # M1 -> VGS1 -> Vtail.
    m1 = _solve_vgs(
        oracle, polarity="nmos", target_current_a=i1_a,
        width_um=w_m1_um, length_um=length_um,
        vds_from_vgs=lambda vgs: n1_v - (vin_cm_v - vgs),
        vgs_min_v=0.35, vgs_max_v=min(1.2, vin_cm_v),
        tolerance_a=policy.current_tolerance_a,
    )
    vgs1_v = m1.value
    vtail_v = vin_cm_v - vgs1_v
    if not (vss_v <= vtail_v < n1_v):
        raise ConstructionError("derived Vtail is outside physical bounds")

    # M3 -> W3; W4=W3.
    m3 = _solve_width(
        oracle, polarity="pmos", target_current_a=i3_a,
        length_um=length_um, vgs_abs_v=vdd_v - n1_v,
        vds_abs_v=vdd_v - n1_v,
        width_min_um=policy.width_min_um,
        width_max_um=policy.width_max_um,
        tolerance_a=policy.current_tolerance_a,
    )
    w3_um = w4_um = m3.value

    # M4 -> N2.
    def m4_residual(n2_v: float) -> float:
        if not (vtail_v < n2_v < vdd_v):
            return -i4_a
        return oracle.predict(
            polarity="pmos", width_um=w4_um, length_um=length_um,
            vgs_abs_v=vdd_v - n1_v, vds_abs_v=vdd_v - n2_v,
            vbs_abs_v=0.0, allow_extrapolation=False, persist=False,
        ).id_abs_a - i4_a

    n2_v = _root(m4_residual, max(vtail_v + 0.05, 0.05), vdd_v - 0.05)
    m4 = oracle.predict(
        polarity="pmos", width_um=w4_um, length_um=length_um,
        vgs_abs_v=vdd_v - n1_v, vds_abs_v=vdd_v - n2_v,
        vbs_abs_v=0.0, allow_extrapolation=False, persist=False,
    )

    # M2 check under matched-device construction.
    m2 = oracle.predict(
        polarity="nmos", width_um=w2_um, length_um=length_um,
        vgs_abs_v=vgs1_v, vds_abs_v=n2_v - vtail_v,
        vbs_abs_v=0.0, allow_extrapolation=False, persist=False,
    )
    m2_error = m2.id_abs_a - i2_a
    if abs(m2_error) > policy.current_tolerance_a:
        raise ConstructionError(f"M2 current check failed by {m2_error} A")

    # M5: explicit Vbias policy -> W5.
    m5 = _solve_width(
        oracle, polarity="nmos", target_current_a=i_m5_a,
        length_um=length_um, vgs_abs_v=vbias_v,
        vds_abs_v=vtail_v,
        width_min_um=policy.width_min_um,
        width_max_um=policy.width_max_um,
        tolerance_a=policy.current_tolerance_a,
    )
    w5_um = m5.value

    # Output: one scalar Iout root from the size relation.
    def relation(iout_a: float) -> float:
        m7_local = _solve_width(
            oracle, polarity="nmos", target_current_a=iout_a,
            length_um=length_um, vgs_abs_v=vbias_v,
            vds_abs_v=vout_v,
            width_min_um=policy.width_min_um,
            width_max_um=policy.width_max_um,
            tolerance_a=policy.current_tolerance_a,
        )
        m6_local = _solve_width(
            oracle, polarity="pmos", target_current_a=iout_a,
            length_um=length_um, vgs_abs_v=vdd_v - n2_v,
            vds_abs_v=vdd_v - vout_v,
            width_min_um=policy.width_min_um,
            width_max_um=policy.width_max_um,
            tolerance_a=policy.current_tolerance_a,
        )
        return m6_local.value / w3_um - 2.0 * m7_local.value / w5_um

    # A scalar bracket search is not a design-space scan; it is root bracketing.
    samples = [
        policy.iout_min_a * (policy.iout_max_a / policy.iout_min_a) ** (i / 48)
        for i in range(49)
    ]
    valid = []
    for current in samples:
        try:
            valid.append((current, relation(current)))
        except ConstructionError:
            continue
    bracket = None
    for left, right in zip(valid, valid[1:]):
        if left[1] == 0.0:
            bracket = (left[0], left[0])
            break
        if left[1] * right[1] < 0.0:
            bracket = (left[0], right[0])
            break
    if bracket is None:
        raise ConstructionError("no Iout root for the size relation")

    iout_a = bracket[0] if bracket[0] == bracket[1] else float(
        brentq(relation, bracket[0], bracket[1], xtol=1e-12, rtol=1e-10)
    )
    m7 = _solve_width(
        oracle, polarity="nmos", target_current_a=iout_a,
        length_um=length_um, vgs_abs_v=vbias_v, vds_abs_v=vout_v,
        width_min_um=policy.width_min_um,
        width_max_um=policy.width_max_um,
        tolerance_a=policy.current_tolerance_a,
    )
    m6 = _solve_width(
        oracle, polarity="pmos", target_current_a=iout_a,
        length_um=length_um, vgs_abs_v=vdd_v - n2_v,
        vds_abs_v=vdd_v - vout_v,
        width_min_um=policy.width_min_um,
        width_max_um=policy.width_max_um,
        tolerance_a=policy.current_tolerance_a,
    )
    size_error = m6.value / w3_um - 2.0 * m7.value / w5_um
    if abs(size_error) > policy.relation_tolerance:
        raise ConstructionError("final size relation failed")

    points = {"M1":m1.point,"M2":m2,"M3":m3.point,"M4":m4,
              "M5":m5.point,"M6":m6.point,"M7":m7.point}
    if not all(p.saturated for p in points.values()):
        raise ConstructionError("at least one device is not saturated")
    if not all(p.in_domain for p in points.values()):
        raise ConstructionError("at least one device is outside MLP domain")

    for p in points.values():
        oracle.predict(
            polarity=p.polarity, width_um=p.width_um, length_um=p.length_um,
            vgs_abs_v=p.vgs_abs_v, vds_abs_v=p.vds_abs_v,
            vbs_abs_v=p.vbs_abs_v, allow_extrapolation=False, persist=True,
        )
    oracle.flush_cache()

    return {
        "assignment_id":"deterministic_dependency_assignment_000000",
        "algorithm":"deterministic_dependency_ordered_local_solves",
        "independent_variables":{"i_m5_a":i_m5_a,"w_m1_um":w_m1_um,"vout_v":vout_v},
        "construction_policy":asdict(policy),
        "i_m1_a":i1_a,"i_m2_a":i2_a,"i_m3_a":i3_a,"i_m4_a":i4_a,
        "i_m5_a":i_m5_a,"i_m6_a":iout_a,"i_m7_a":iout_a,
        "w_m1_um":w_m1_um,"w_m2_um":w2_um,"w_m3_um":w3_um,"w_m4_um":w4_um,
        "w_m5_um":w5_um,"w_m6_um":m6.value,"w_m7_um":m7.value,
        "vtail_v":vtail_v,"n1_v":n1_v,"n2_v":n2_v,"vbias_v":vbias_v,
        "vout_v":vout_v,"vdd_v":vdd_v,"vss_v":vss_v,"vin_cm_v":vin_cm_v,
        "m2_current_residual_a":m2_error,"size_relation_residual":size_error,
        "device_points":{name:asdict(point) for name,point in points.items()},
    }

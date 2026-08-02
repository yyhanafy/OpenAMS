"""Reduced circuit-level small-signal AC estimate for the two-stage op amp.

Approximations:
- gm and gds come from the continuous dense MLP.
- Cgs/Cgd/Cdb/Csb come from nearest-bias capacitance density in the dense table.
- Supply, body, and Vbias are AC ground.
- Miller capacitor is stamped between N2 and OUT.
- Load capacitor is stamped from OUT to ground.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from openams.validation.dense_capacitance_lookup import DenseCapacitanceLookup


@dataclass(frozen=True)
class AcMetrics:
    gain_db: float | None
    ugb_hz: float | None
    phase_margin_deg: float | None
    phase_at_ugb_deg: float | None
    min_cap_lookup_distance: float
    max_cap_lookup_distance: float


UNKNOWN = ("n1", "n2", "out", "vtail")
INDEX = {name: idx for idx, name in enumerate(UNKNOWN)}
GROUND = {"0", "vdd", "vss", "vbias", "body"}


def _stamp_branch(
    matrix: np.ndarray,
    rhs: np.ndarray,
    a: str,
    b: str,
    admittance: complex,
    known: Mapping[str, complex],
) -> None:
    """Stamp y*(Va-Vb) between arbitrary known/unknown nodes."""

    def add_equation(node: str, other: str, sign: complex) -> None:
        if node in GROUND or node in known:
            return
        row = INDEX[node]
        matrix[row, row] += sign * admittance
        if other in INDEX:
            matrix[row, INDEX[other]] -= sign * admittance
        elif other in known:
            rhs[row] += sign * admittance * known[other]
        # Ground contributes zero.

    add_equation(a, b, 1.0)
    add_equation(b, a, 1.0)


def _stamp_gm(
    matrix: np.ndarray,
    rhs: np.ndarray,
    *,
    drain: str,
    gate: str,
    source: str,
    gm_signed: float,
    known: Mapping[str, complex],
) -> None:
    """Stamp drain-to-source controlled current gm*(Vg-Vs)."""

    for node, sign in ((drain, 1.0), (source, -1.0)):
        if node not in INDEX:
            continue
        row = INDEX[node]

        if gate in INDEX:
            matrix[row, INDEX[gate]] += sign * gm_signed
        elif gate in known:
            rhs[row] -= sign * gm_signed * known[gate]

        if source in INDEX:
            matrix[row, INDEX[source]] -= sign * gm_signed
        elif source in known:
            rhs[row] += sign * gm_signed * known[source]


def estimate_two_stage_ac(
    assignment: Mapping[str, Any],
    cap_lookup: DenseCapacitanceLookup,
    *,
    frequencies_hz: np.ndarray,
    c_miller_f: float = 3e-12,
    c_load_f: float = 10e-12,
) -> AcMetrics:
    device_nodes = {
        "M1": ("n1", "inp", "vtail", "nmos"),
        "M2": ("n2", "inn", "vtail", "nmos"),
        "M3": ("n1", "n1", "vdd", "pmos"),
        "M4": ("n2", "n1", "vdd", "pmos"),
        "M5": ("vtail", "vbias", "vss", "nmos"),
        "M6": ("out", "n2", "vdd", "pmos"),
        "M7": ("out", "vbias", "vss", "nmos"),
    }

    points = assignment["device_points"]
    caps = {}
    distances = []

    for device, (_, _, _, polarity) in device_nodes.items():
        point = points[device]
        cap = cap_lookup.lookup(
            polarity=polarity,
            width_um=float(point["width_um"]),
            vgs_abs_v=float(point["vgs_abs_v"]),
            vds_abs_v=float(point["vds_abs_v"]),
            vbs_abs_v=float(point.get("vbs_abs_v", 0.0)),
        )
        caps[device] = cap
        distances.append(cap.distance)

    response = np.empty(len(frequencies_hz), dtype=np.complex128)

    for freq_index, frequency in enumerate(frequencies_hz):
        s = 1j * 2.0 * np.pi * frequency
        matrix = np.zeros((len(UNKNOWN), len(UNKNOWN)), dtype=np.complex128)
        rhs = np.zeros(len(UNKNOWN), dtype=np.complex128)
        known = {
            "inp": 0.5 + 0j,
            "inn": -0.5 + 0j,
            "vdd": 0j,
            "vss": 0j,
            "vbias": 0j,
            "body": 0j,
        }

        for device, (drain, gate, source, polarity) in device_nodes.items():
            point = points[device]
            gm = float(point["gm_s"])
            gds = max(float(point["gds_s"]), 0.0)
            gm_signed = gm if polarity == "nmos" else -gm

            _stamp_branch(matrix, rhs, drain, source, gds, known)
            _stamp_gm(
                matrix,
                rhs,
                drain=drain,
                gate=gate,
                source=source,
                gm_signed=gm_signed,
                known=known,
            )

            cap = caps[device]
            _stamp_branch(matrix, rhs, gate, source, s * cap.cgs_f, known)
            _stamp_branch(matrix, rhs, gate, drain, s * cap.cgd_f, known)
            _stamp_branch(matrix, rhs, drain, "body", s * cap.cdb_f, known)
            _stamp_branch(matrix, rhs, source, "body", s * cap.csb_f, known)

        _stamp_branch(matrix, rhs, "n2", "out", s * c_miller_f, known)
        _stamp_branch(matrix, rhs, "out", "0", s * c_load_f, known)

        try:
            solution = np.linalg.solve(matrix, rhs)
            response[freq_index] = solution[INDEX["out"]]
        except np.linalg.LinAlgError:
            response[freq_index] = np.nan + 1j * np.nan

    finite = np.isfinite(response.real) & np.isfinite(response.imag)
    if not np.any(finite):
        return AcMetrics(
            gain_db=None,
            ugb_hz=None,
            phase_margin_deg=None,
            phase_at_ugb_deg=None,
            min_cap_lookup_distance=min(distances),
            max_cap_lookup_distance=max(distances),
        )

    magnitude = np.abs(response)
    gain_db_curve = 20.0 * np.log10(np.maximum(magnitude, 1e-300))
    gain_db = float(gain_db_curve[np.flatnonzero(finite)[0]])

    # Normalize low-frequency phase to 0 degrees so PM is referenced to the
    # low-frequency amplifier sign.
    first = np.flatnonzero(finite)[0]
    normalized = response * np.exp(-1j * np.angle(response[first]))
    phase_deg = np.unwrap(np.angle(normalized)) * 180.0 / np.pi

    crossing = None
    for index in range(first + 1, len(frequencies_hz)):
        if not finite[index - 1] or not finite[index]:
            continue
        if gain_db_curve[index - 1] >= 0.0 and gain_db_curve[index] <= 0.0:
            crossing = index
            break

    if crossing is None:
        ugb_hz = None
        phase_at = None
        phase_margin = None
    else:
        x0 = np.log10(frequencies_hz[crossing - 1])
        x1 = np.log10(frequencies_hz[crossing])
        y0 = gain_db_curve[crossing - 1]
        y1 = gain_db_curve[crossing]
        fraction = 0.0 if y1 == y0 else (0.0 - y0) / (y1 - y0)
        ugb_hz = float(10.0 ** (x0 + fraction * (x1 - x0)))
        phase_at = float(
            phase_deg[crossing - 1]
            + fraction * (phase_deg[crossing] - phase_deg[crossing - 1])
        )
        phase_margin = float(180.0 + phase_at)

    return AcMetrics(
        gain_db=gain_db,
        ugb_hz=ugb_hz,
        phase_margin_deg=phase_margin,
        phase_at_ugb_deg=phase_at,
        min_cap_lookup_distance=min(distances),
        max_cap_lookup_distance=max(distances),
    )

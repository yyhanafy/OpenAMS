from __future__ import annotations

from openams.synthesis.complete_assignments import (
    TechRow,
    _interpolate_m6,
    _minimum_nf,
)


def test_minimum_nf() -> None:
    policy = {
        "total_min_um": 0.42,
        "total_max_um": 300.0,
        "finger_min_um": 0.42,
        "finger_max_um": 100.0,
        "nf_min": 1,
        "nf_max": 3,
    }
    assert _minimum_nf(250.0, policy) == 3


def test_density_interpolation() -> None:
    rows = [
        TechRow(1, "pmos", "p", 0.5, 10.0, 0.7, 0.8, 0.0, 10e-6, True),
        TechRow(2, "pmos", "p", 0.5, 10.0, 0.8, 0.8, 0.0, 20e-6, True),
    ]
    result = _interpolate_m6(rows, 1.5e-6)
    assert result is not None
    assert abs(result["vgs_v"] - 0.75) < 1e-12
    assert abs(result["interpolation_fraction"] - 0.5) < 1e-12

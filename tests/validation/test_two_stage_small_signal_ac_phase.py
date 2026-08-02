import math

from openams.validation.two_stage_small_signal_ac import normalize_phase_deg


def test_normalize_observed_unwrapped_phase() -> None:
    phase = normalize_phase_deg(207.967)
    assert math.isclose(phase, -152.033, abs_tol=1e-12)
    assert math.isclose(180.0 + phase, 27.967, abs_tol=1e-12)


def test_normalize_phase_principal_range() -> None:
    assert normalize_phase_deg(0.0) == 0.0
    assert normalize_phase_deg(180.0) == -180.0
    assert normalize_phase_deg(-180.0) == -180.0
    assert normalize_phase_deg(540.0) == -180.0

from __future__ import annotations

from openams.synthesis.dependent_regions import (
    _clip_interval,
    _intersect,
    _scale_interval,
)


def test_interval_scaling() -> None:
    assert _scale_interval({"minimum": 10.0, "maximum": 20.0}, 0.5) == {
        "minimum": 5.0,
        "maximum": 10.0,
    }


def test_interval_intersection() -> None:
    assert _intersect(
        {"minimum": 0.5, "maximum": 1.5},
        {"minimum": 0.6, "maximum": 1.6},
    ) == {"minimum": 0.6, "maximum": 1.5}


def test_physical_clipping() -> None:
    assert _clip_interval(
        {"minimum": -0.1, "maximum": 0.4},
        0.0,
        0.9,
    ) == {"minimum": 0.0, "maximum": 0.4}

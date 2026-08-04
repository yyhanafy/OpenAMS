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

from openams.synthesis.generic_dependency import _eval_interval, propagate_linear_intervals
import pytest


def test_generic_interval_expression_propagation() -> None:
    values={"i_m3":{"minimum":20e-6,"maximum":40e-6}}
    result=_eval_interval("1.5 * i_m3",values)
    assert result["minimum"] == pytest.approx(30e-6)
    assert result["maximum"] == pytest.approx(60e-6)


def test_generic_current_dependency_chain() -> None:
    intent={"circuit_intent":{"current_relations":[
        {"id":"a","equation":"i_m1 = 0.5 * i_m3"},
        {"id":"b","equation":"i_m4 = 1.5 * i_m3"},
        {"id":"c","equation":"i_m6 = i_m4 - i_m1"},
    ]}}
    seeds={"i_m3_a":{"technology_minimum":20e-6,"technology_maximum":40e-6}}
    values,_=propagate_linear_intervals(intent,seeds)
    assert values["i_m1_a"]["minimum"] == pytest.approx(10e-6)
    assert values["i_m1_a"]["maximum"] == pytest.approx(20e-6)
    assert values["i_m6_a"]["minimum"] == pytest.approx(10e-6)
    assert values["i_m6_a"]["maximum"] == pytest.approx(50e-6)

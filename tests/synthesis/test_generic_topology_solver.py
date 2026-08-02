from __future__ import annotations

from openams.synthesis.generic_topology_solver import (
    SafeExpression,
    TechnologyRow,
    _close,
    _interpolate_density,
)


def test_safe_expression() -> None:
    expr = SafeExpression("density7 * w5 / (2 * w4)")
    value = expr.evaluate(
        {"density7": 2.0, "w5": 4.0, "w4": 8.0}
    )
    assert value == 0.5


def test_tolerance() -> None:
    assert _close(10.5e-6, 10e-6, atol=1e-6, rtol=0.1)


def test_density_interpolation() -> None:
    rows = [
        TechnologyRow(
            1, "pmos", "p", 0.5, 10.0,
            0.7, 0.8, 0.0, 10e-6, 0.2, True,
        ),
        TechnologyRow(
            2, "pmos", "p", 0.5, 10.0,
            0.8, 0.8, 0.0, 20e-6, 0.25, True,
        ),
    ]
    result = _interpolate_density(rows, 1.5e-6)
    assert result is not None
    assert abs(result["vgs_v"] - 0.75) < 1e-12
    assert abs(result["vdsat_v"] - 0.225) < 1e-12


def test_contract_primitives_are_generic() -> None:
    from openams.synthesis.generic_topology_solver import Constraint
    assert Constraint({"id": "copy", "kind": "copy_device_row"}).kind == "copy_device_row"
    assert Constraint({"id": "density", "kind": "row_density"}).kind == "row_density"


def test_matched_operating_point_primitive_is_available() -> None:
    from openams.synthesis.generic_topology_solver import Constraint
    constraint = Constraint({
        "id": "pair_match",
        "kind": "matched_operating_point",
        "left_device": "M1",
        "right_device": "M2",
    })
    assert constraint.kind == "matched_operating_point"


def test_copy_width_realization_primitive_is_available() -> None:
    from openams.synthesis.generic_topology_solver import Constraint
    constraint = Constraint({
        "id": "copy_width",
        "kind": "copy_width_realization",
        "source_device": "M1",
        "target_device": "M2",
    })
    assert constraint.kind == "copy_width_realization"

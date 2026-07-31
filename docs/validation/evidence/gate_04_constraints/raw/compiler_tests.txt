from dataclasses import dataclass

import pytest

from openams.synthesis import (
    CircuitConstraintCompiler,
    FieldRelationConstraint,
    RegionBinding,
    RegionInput,
    SumConstraint,
    SynthesisError,
)


@dataclass(frozen=True)
class CanonicalConstraint:
    name: str
    kind: str
    expression: str
    source: str = "design_intent"


def binding(name, rows, mapping):
    return RegionBinding(name, RegionInput(name, tuple(rows)), mapping)


def test_compiles_exact_device_equality_and_builds_indexed_region():
    compiler = CircuitConstraintCompiler()
    compiled = compiler.compile(
        [CanonicalConstraint("mirror_current", "equality", "device.M3.current == device.M4.current")],
        [
            binding("M3", [{"id": 1.0}, {"id": 2.0}], {"device.M3.current": "id"}),
            binding("M4", [{"id": 2.0}, {"id": 3.0}], {"device.M4.current": "id"}),
        ],
    )
    assert isinstance(compiled.constraints[0], FieldRelationConstraint)
    result = compiled.build()
    assert result.retained_count == 1
    assert result.rows[0].values["M3.id"] == 2.0
    assert result.metadata["intersection_method"] == "planned_indexed_equality_join"


def test_compiles_scaled_relation():
    compiled = CircuitConstraintCompiler().compile(
        [CanonicalConstraint("ratio", "equality", "device.M6.width == 2 * device.M7.width")],
        [
            binding("M6", [{"w": 4.0}], {"device.M6.width": "w"}),
            binding("M7", [{"w": 2.0}], {"device.M7.width": "w"}),
        ],
    )
    relation = compiled.constraints[0]
    assert isinstance(relation, FieldRelationConstraint)
    assert relation.scale == 2.0
    assert compiled.build().retained_count == 1


def test_compiles_kcl_sum():
    compiled = CircuitConstraintCompiler().compile(
        [CanonicalConstraint("tail_kcl", "topology_derived", "device.M5.current == device.M1.current + device.M2.current")],
        [
            binding("M1", [{"id": 1.0}], {"device.M1.current": "id"}),
            binding("M2", [{"id": 2.0}], {"device.M2.current": "id"}),
            binding("M5", [{"id": 3.0}], {"device.M5.current": "id"}),
        ],
    )
    assert isinstance(compiled.constraints[0], SumConstraint)
    assert compiled.build().retained_count == 1


def test_preserves_constraint_source_in_diagnostics():
    compiled = CircuitConstraintCompiler().compile(
        [CanonicalConstraint("match", "equality", "device.M1.width == device.M2.width", "design_rules")],
        [
            binding("M1", [{"w": 1.0}], {"device.M1.width": "w"}),
            binding("M2", [{"w": 1.0}], {"device.M2.width": "w"}),
        ],
    )
    assert compiled.diagnostics[0].status == "compiled"
    assert compiled.diagnostics[0].source == "design_rules"


def test_unbound_variable_is_explicit_error():
    with pytest.raises(SynthesisError, match="unbound canonical variable"):
        CircuitConstraintCompiler().compile(
            [CanonicalConstraint("bad", "equality", "device.M1.width == device.M2.width")],
            [binding("M1", [{"w": 1.0}], {"device.M1.width": "w"})],
        )


def test_non_strict_mode_reports_unsupported_constraint():
    compiled = CircuitConstraintCompiler().compile(
        [CanonicalConstraint("range", "range", "device.M1.width >= 1")],
        [binding("M1", [{"w": 1.0}], {"device.M1.width": "w"})],
        strict=False,
    )
    assert compiled.constraints == ()
    assert compiled.diagnostics[0].status == "unsupported"


def test_duplicate_canonical_binding_is_rejected():
    with pytest.raises(Exception, match="bound to both"):
        CircuitConstraintCompiler().compile(
            [],
            [
                binding("A", [{"x": 1}], {"shared": "x"}),
                binding("B", [{"x": 1}], {"shared": "x"}),
            ],
        )


def test_nonlinear_expression_is_rejected():
    with pytest.raises(SynthesisError, match="not linear"):
        CircuitConstraintCompiler().compile(
            [CanonicalConstraint("nonlinear", "equality", "device.M1.current == device.M2.width * device.M2.vgs")],
            [
                binding("M1", [{"id": 1.0}], {"device.M1.current": "id"}),
                binding("M2", [{"w": 1.0, "vgs": 1.0}], {"device.M2.width": "w", "device.M2.vgs": "vgs"}),
            ],
        )

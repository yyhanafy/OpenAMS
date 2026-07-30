"""Compile canonical circuit constraints into explicit region intersections."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .constraints import CircuitConstraint, FieldRelationConstraint, SumConstraint
from .errors import InvalidRegionError, SynthesisError
from .indexed import PlannedIntersectionPolicy, PlannedRegionIntersection
from .model import CircuitRegion, RegionInput


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


def _freeze(mapping: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class RegionBinding:
    """Bind canonical circuit-variable names to one explicit input region.

    ``field_map`` maps canonical names, such as ``device.M1.width``, to local
    row fields, such as ``width``.  The emitted synthesis field is namespaced
    with ``region_name``.
    """

    region_name: str
    region: RegionInput
    field_map: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.region_name.strip():
            raise InvalidRegionError("binding region_name must be non-empty")
        if self.region.name != self.region_name:
            raise InvalidRegionError(
                f"binding name {self.region_name!r} does not match RegionInput name {self.region.name!r}"
            )
        if not self.field_map:
            raise InvalidRegionError("binding field_map must not be empty")
        object.__setattr__(self, "field_map", _freeze(self.field_map))

    def synthesis_field(self, canonical_name: str) -> str | None:
        local = self.field_map.get(canonical_name)
        return None if local is None else f"{self.region_name}.{local}"


@dataclass(frozen=True)
class ConstraintCompilationDiagnostic:
    constraint_name: str
    status: str
    message: str
    source: str = ""


@dataclass(frozen=True)
class CompiledIntersection:
    inputs: tuple[RegionInput, ...]
    constraints: tuple[CircuitConstraint, ...]
    diagnostics: tuple[ConstraintCompilationDiagnostic, ...]
    canonical_to_synthesis: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_to_synthesis", MappingProxyType(dict(self.canonical_to_synthesis)))

    def build(
        self,
        policy: PlannedIntersectionPolicy | None = None,
    ) -> CircuitRegion:
        return PlannedRegionIntersection(self.constraints, policy=policy).build(self.inputs)


class CircuitConstraintCompiler:
    """Translate canonical, data-only constraints into synthesis predicates.

    The compiler intentionally accepts any object exposing ``name``, ``kind``,
    ``expression`` and optional ``source`` attributes.  This keeps synthesis
    decoupled from the concrete immutable model implementation.
    """

    def compile(
        self,
        constraints: Iterable[Any],
        bindings: Sequence[RegionBinding],
        *,
        strict: bool = True,
    ) -> CompiledIntersection:
        bound = tuple(bindings)
        if not bound:
            raise InvalidRegionError("constraint compilation requires at least one region binding")
        names = tuple(item.region_name for item in bound)
        if len(set(names)) != len(names):
            raise InvalidRegionError("region binding names must be unique")

        canonical: dict[str, str] = {}
        for binding in bound:
            for variable, local in binding.field_map.items():
                target = f"{binding.region_name}.{local}"
                previous = canonical.setdefault(variable, target)
                if previous != target:
                    raise InvalidRegionError(
                        f"canonical variable {variable!r} is bound to both {previous!r} and {target!r}"
                    )

        compiled: list[CircuitConstraint] = []
        diagnostics: list[ConstraintCompilationDiagnostic] = []
        for raw in constraints:
            name = str(getattr(raw, "name", "")).strip()
            kind = str(getattr(raw, "kind", "")).strip().lower()
            expression = str(getattr(raw, "expression", "")).strip()
            source = str(getattr(raw, "source", "") or "")
            if not name or not expression:
                raise SynthesisError("canonical constraints require non-empty name and expression")
            try:
                item = self._compile_one(name, kind, expression, canonical)
            except SynthesisError as exc:
                diagnostics.append(ConstraintCompilationDiagnostic(name, "unsupported", str(exc), source))
                if strict:
                    raise
                continue
            compiled.append(item)
            diagnostics.append(ConstraintCompilationDiagnostic(name, "compiled", type(item).__name__, source))

        compiled_names = tuple(item.name for item in compiled)
        if len(set(compiled_names)) != len(compiled_names):
            raise SynthesisError("compiled synthesis constraint names must be unique")
        return CompiledIntersection(
            inputs=tuple(item.region for item in bound),
            constraints=tuple(compiled),
            diagnostics=tuple(diagnostics),
            canonical_to_synthesis=canonical,
        )

    def _compile_one(
        self,
        name: str,
        kind: str,
        expression: str,
        mapping: Mapping[str, str],
    ) -> CircuitConstraint:
        if kind not in {"", "equality", "topology_derived"}:
            raise SynthesisError(f"constraint {name!r}: unsupported kind {kind!r}")
        left_text, right_text = self._split_equality(name, expression)
        left = self._field(name, left_text, mapping)

        # Direct or affine relation: left == scale*right + offset.
        affine = self._affine(right_text, mapping)
        if affine is not None:
            scale, right, offset = affine
            return FieldRelationConstraint(left, right, scale=scale, offset=offset, label=name)

        # General linear sum: left == c1*x1 + c2*x2 + constant.
        terms, offset = self._linear_sum(name, right_text, mapping)
        return SumConstraint(left, tuple(terms), offset=offset, label=name)

    @staticmethod
    def _split_equality(name: str, expression: str) -> tuple[str, str]:
        if expression.count("==") != 1:
            raise SynthesisError(f"constraint {name!r}: only one == equality is supported")
        left, right = (part.strip() for part in expression.split("==", 1))
        if not left or not right:
            raise SynthesisError(f"constraint {name!r}: invalid equality expression")
        return left, right

    @staticmethod
    def _field(name: str, token: str, mapping: Mapping[str, str]) -> str:
        if not _NAME.fullmatch(token):
            raise SynthesisError(f"constraint {name!r}: left side must be one canonical variable")
        try:
            return mapping[token]
        except KeyError as exc:
            raise SynthesisError(f"constraint {name!r}: unbound canonical variable {token!r}") from exc

    @staticmethod
    def _affine(text: str, mapping: Mapping[str, str]) -> tuple[float, str, float] | None:
        try:
            node = ast.parse(text, mode="eval").body
        except SyntaxError:
            return None
        parsed = _linearize(node)
        if parsed is None:
            return None
        coefficients, constant = parsed
        if len(coefficients) != 1:
            return None
        variable, coefficient = next(iter(coefficients.items()))
        if variable not in mapping:
            return None
        return coefficient, mapping[variable], constant

    @staticmethod
    def _linear_sum(
        name: str,
        text: str,
        mapping: Mapping[str, str],
    ) -> tuple[list[tuple[float, str]], float]:
        try:
            node = ast.parse(text, mode="eval").body
        except SyntaxError as exc:
            raise SynthesisError(f"constraint {name!r}: invalid right-side expression") from exc
        parsed = _linearize(node)
        if parsed is None:
            raise SynthesisError(f"constraint {name!r}: expression is not linear")
        coefficients, constant = parsed
        if not coefficients:
            raise SynthesisError(f"constraint {name!r}: constant-only equality is not a region join")
        terms: list[tuple[float, str]] = []
        for variable, coefficient in sorted(coefficients.items()):
            if variable not in mapping:
                raise SynthesisError(f"constraint {name!r}: unbound canonical variable {variable!r}")
            terms.append((coefficient, mapping[variable]))
        return terms, constant


def _variable_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: list[str] = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _linearize(node: ast.AST) -> tuple[dict[str, float], float] | None:
    variable = _variable_name(node)
    if variable is not None:
        return {variable: 1.0}, 0.0
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return {}, float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _linearize(node.operand)
        if value is None:
            return None
        factor = -1.0 if isinstance(node.op, ast.USub) else 1.0
        return ({name: factor * coefficient for name, coefficient in value[0].items()}, factor * value[1])
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        left = _linearize(node.left)
        right = _linearize(node.right)
        if left is None or right is None:
            return None
        factor = -1.0 if isinstance(node.op, ast.Sub) else 1.0
        coefficients = dict(left[0])
        for name, coefficient in right[0].items():
            coefficients[name] = coefficients.get(name, 0.0) + factor * coefficient
            if coefficients[name] == 0.0:
                del coefficients[name]
        return coefficients, left[1] + factor * right[1]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _linearize(node.left)
        right = _linearize(node.right)
        if left is None or right is None:
            return None
        if left[0] and right[0]:
            return None
        if not left[0]:
            factor = left[1]
            return ({name: factor * coefficient for name, coefficient in right[0].items()}, factor * right[1])
        factor = right[1]
        return ({name: factor * coefficient for name, coefficient in left[0].items()}, factor * left[1])
    return None

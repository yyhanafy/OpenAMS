"""Topology-generic Step 5 complete-assignment enumeration.

The engine is intentionally split into four topology-independent layers:

1. Enumerate independent-variable domains.
2. Propagate compiled scalar equations.
3. Ask a pluggable device provider for technology-consistent realizations.
4. Enforce declarative circuit invariants and emit model-valid assignments.

A device provider may be table-backed, MLP-backed, or any future surrogate.
The default provider in this module is the characterized-table provider.
"""
from __future__ import annotations

import ast
import csv
import importlib
import itertools
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Protocol, Sequence

CURRENT_TOKEN_RE = re.compile(r"\bdevice\.([A-Za-z_][A-Za-z0-9_]*)\.current\b")


class GenericStep5Error(ValueError):
    """Raised when generic complete-assignment synthesis cannot proceed."""




WIDTH_BUCKET_UM = 1.0
VOLTAGE_BUCKET_V = 0.020
CURRENT_BUCKET_A = 1e-6

def _bucket_value(name: str, value: Any) -> Any:
    if not isinstance(value, (int, float)):
        return value
    v=float(value)
    if name.startswith("w_") and name.endswith("_um"):
        return round(v / WIDTH_BUCKET_UM)
    if name.startswith("i_") and name.endswith("_a"):
        return round(v / CURRENT_BUCKET_A)
    if name.endswith("_v"):
        return round(v / VOLTAGE_BUCKET_V)
    return value

def _branch_key(state: "SearchState") -> tuple[Any, ...]:
    values = tuple(sorted(
        (k, _bucket_value(k, v))
        for k, v in state.values.items()
        if isinstance(v, (int, float))
    ))
    return (int(state.group_index), values)
@dataclass(frozen=True)
class DeviceRequest:
    device: str
    model: str
    polarity: str
    length_um: float
    target_current_a: float
    fixed_width_um: float | None
    known_vgs_v: float | None
    known_vds_v: float | None
    known_vbs_v: float | None
    known_gate_v: float | None
    known_drain_v: float | None
    known_source_v: float | None
    known_bulk_v: float | None
    require_saturation: bool


@dataclass(frozen=True)
class DeviceRealization:
    width_um: float
    nf: int
    finger_width_um: float
    predicted_current_a: float
    vgs_v: float
    vds_v: float
    vbs_v: float
    vdsat_v: float | None
    saturated: bool
    provenance: Mapping[str, Any]




def _freeze_exact(value: Any) -> Any:
    """Convert nested Step 5 state data into a deterministic exact hash key."""
    if isinstance(value, float):
        return ("float", value.hex())
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _freeze_exact(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_exact(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze_exact(item) for item in value), key=repr))
    return value


@dataclass(frozen=True)
class SearchState:
    """Behavior-preserving snapshot of one Step 5 recursion node."""

    group_index: int
    values: Mapping[str, float]
    nodes: Mapping[str, float]
    provenance: Mapping[str, Any]

    def exact_key(self) -> tuple[Any, ...]:
        """Return a lossless key suitable for later exact memoization."""
        return (
            int(self.group_index),
            _freeze_exact(self.values),
            _freeze_exact(self.nodes),
            _freeze_exact(self.provenance),
        )


@dataclass(frozen=True)
class OperatingRegion:
    """Validated terminal region before serialization as an assignment."""

    values: Mapping[str, float]
    device_technology_provenance: Mapping[str, Any]
    assignment_semantics: str
    physical_proof_level: str
    route: str
    multiplicity: int = 1

    def to_assignment(self) -> dict[str, Any]:
        return {
            **dict(self.values),
            "device_technology_provenance": dict(self.device_technology_provenance),
            "assignment_semantics": self.assignment_semantics,
            "physical_proof_level": self.physical_proof_level,
            "route": self.route,
        }


@dataclass
class SearchProfile:
    """Instrumentation for the generic Step 5 search tree."""

    recursion_nodes: int = 0
    terminal_states: int = 0
    accepted_solutions: int = 0
    max_depth: int = 0
    solution_limit_hits: int = 0
    unique_exact_states: int = 0
    repeated_exact_states_observed: int = 0
    pruned_branch_states: int = 0
    group_calls: Counter[str] = field(default_factory=Counter)
    group_choices: Counter[str] = field(default_factory=Counter)
    group_empty: Counter[str] = field(default_factory=Counter)
    rejection_counts: Counter[str] = field(default_factory=Counter)

    def record_rejection(self, reason: str, count: int = 1) -> None:
        self.rejection_counts[str(reason)] += int(count)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recursion_nodes": self.recursion_nodes,
            "terminal_states": self.terminal_states,
            "accepted_solutions": self.accepted_solutions,
            "max_depth": self.max_depth,
            "solution_limit_hits": self.solution_limit_hits,
            "unique_exact_states": self.unique_exact_states,
            "repeated_exact_states_observed": self.repeated_exact_states_observed,
            "pruned_branch_states": self.pruned_branch_states,
            "group_calls": dict(sorted(self.group_calls.items())),
            "group_choices": dict(sorted(self.group_choices.items())),
            "group_empty": dict(sorted(self.group_empty.items())),
            "rejection_counts": dict(sorted(self.rejection_counts.items())),
        }


class DeviceProvider(Protocol):
    name: str

    def candidates(
        self,
        request: DeviceRequest,
        *,
        current_relative_tolerance: float,
        current_absolute_tolerance_a: float,
        voltage_tolerance_v: float,
        width_policy: Mapping[str, float | int],
        limit: int,
    ) -> Sequence[DeviceRealization]: ...


@dataclass(frozen=True)
class TableRow:
    index: int
    polarity: str
    model: str
    length_um: float
    width_um: float
    vgs_v: float
    vds_v: float
    vbs_v: float
    id_a: float
    vdsat_v: float | None
    saturated: bool

    @property
    def density_a_per_um(self) -> float:
        return self.id_a / self.width_um


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GenericStep5Error(f"{name} must be numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise GenericStep5Error(f"{name} must be finite: {value!r}")
    return result


def _optional_number(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return float(value)
    return None


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _minimum_nf(width_um: float, policy: Mapping[str, float | int]) -> int | None:
    if not float(policy["total_min_um"]) <= width_um <= float(policy["total_max_um"]):
        return None
    for nf in range(int(policy["nf_min"]), int(policy["nf_max"]) + 1):
        finger = width_um / nf
        if float(policy["finger_min_um"]) <= finger <= float(policy["finger_max_um"]):
            return nf
    return None


class TableDeviceProvider:
    name = "characterized_table"

    def __init__(self, path: Path):
        self.path = path.resolve()
        with self.path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            self.rows = tuple(
                TableRow(
                    index=index,
                    polarity=str(row["polarity"]).lower(),
                    model=str(row["model"]),
                    length_um=_number(row["length_um"], "length_um"),
                    width_um=_number(row["width_um"], "width_um"),
                    vgs_v=_number(row.get("vgs_v", row.get("vgs_abs_v")), "vgs"),
                    vds_v=_number(row.get("vds_v", row.get("vds_abs_v")), "vds"),
                    vbs_v=_number(row.get("vbs_v", row.get("vbs_abs_v")), "vbs"),
                    id_a=_number(row.get("id_abs_a", row.get("id_a", row.get("id"))), "id"),
                    vdsat_v=_optional_number(row, "vdsat_abs_v", "vdsat_v", "vdsat"),
                    saturated=_truth(row.get("saturated", True)),
                )
                for index, row in enumerate(reader)
            )
        if not self.rows:
            raise GenericStep5Error(f"empty technology table: {self.path}")

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
        scored: list[tuple[tuple[float, float, float, int], DeviceRealization]] = []
        allowed_current_error = max(
            current_absolute_tolerance_a,
            current_relative_tolerance * max(abs(request.target_current_a), 1e-30),
        )
        for row in self.rows:
            if row.model != request.model or row.polarity != request.polarity:
                continue
            if not math.isclose(row.length_um, request.length_um, rel_tol=0.0, abs_tol=1e-12):
                continue
            if request.require_saturation and not row.saturated:
                continue
            width = request.fixed_width_um or request.target_current_a / row.density_a_per_um
            nf = _minimum_nf(width, width_policy)
            if nf is None:
                continue
            predicted = row.density_a_per_um * width
            current_error = abs(predicted - request.target_current_a)
            if current_error > allowed_current_error:
                continue
            voltage_errors = [
                abs(row.vgs_v - request.known_vgs_v) if request.known_vgs_v is not None else 0.0,
                abs(row.vds_v - request.known_vds_v) if request.known_vds_v is not None else 0.0,
                abs(row.vbs_v - request.known_vbs_v) if request.known_vbs_v is not None else 0.0,
            ]
            max_voltage_error = max(voltage_errors)
            realization = DeviceRealization(
                width_um=width,
                nf=nf,
                finger_width_um=width / nf,
                predicted_current_a=predicted,
                vgs_v=row.vgs_v,
                vds_v=row.vds_v,
                vbs_v=row.vbs_v,
                vdsat_v=row.vdsat_v,
                saturated=row.saturated,
                provenance={
                    "provider": self.name,
                    "technology_row_index": row.index,
                    "technology_source": str(self.path),
                    "current_absolute_error_a": current_error,
                    "current_relative_error": current_error / max(abs(request.target_current_a), 1e-30),
                    "maximum_voltage_mismatch_v": max_voltage_error,
                    "voltage_fit_status": (
                        "WITHIN_DECLARED_TOLERANCE"
                        if max_voltage_error <= voltage_tolerance_v
                        else "PROVISIONAL"
                    ),
                },
            )
            scored.append(
                (
                    (
                        current_error / max(abs(request.target_current_a), 1e-30),
                        max_voltage_error,
                        sum(voltage_errors),
                        row.index,
                    ),
                    realization,
                )
            )
        scored.sort(key=lambda item: item[0])
        return [item[1] for item in scored[:limit]]


class PluginDeviceProvider:
    """Adapter for an MLP or other external provider.

    The plugin target must be ``module:function``. The function receives a
    DeviceRequest and keyword arguments identical to ``DeviceProvider.candidates``.
    It must return DeviceRealization objects or dictionaries with matching keys.
    """

    def __init__(self, target: str):
        module_name, separator, function_name = target.partition(":")
        if not separator:
            raise GenericStep5Error("provider plugin must use module:function syntax")
        self._function = getattr(importlib.import_module(module_name), function_name)
        self.name = f"python_plugin:{target}"

    def candidates(self, request: DeviceRequest, **kwargs: Any) -> Sequence[DeviceRealization]:
        result = self._function(request=request, **kwargs)
        return [item if isinstance(item, DeviceRealization) else DeviceRealization(**item) for item in result]


def _device_map(model: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in model["topology"]["devices"]:
        if str(item.get("kind", "")).lower() != "mos":
            continue
        raw = str(item["name"])
        name = raw[1:] if raw.upper().startswith("X") else raw
        result[name.upper()] = item
    return result


def _polarity(model_name: str) -> str:
    token = model_name.lower()
    if "pfet" in token or "pmos" in token:
        return "pmos"
    if "nfet" in token or "nmos" in token:
        return "nmos"
    raise GenericStep5Error(f"cannot infer polarity from {model_name!r}")


def _width_policy(model: Mapping[str, Any]) -> dict[str, float | int]:
    parameterization = model["project_inputs"]["design_intent"]["synthesis_parameterization"]
    policy = parameterization.get("dependent_width_realization", {})
    rules = model["project_inputs"]["design_rules"]["device_constraints"]["all_mos"]
    return {
        "total_min_um": float(policy.get("total_width_min_um", rules["width_min_um"])),
        "total_max_um": float(policy.get("total_width_max_um", rules["width_max_um"])),
        "finger_min_um": float(policy.get("finger_width_min_um", rules["width_min_um"])),
        "finger_max_um": float(policy.get("finger_width_max_um", rules["width_max_um"])),
        "nf_min": int(policy.get("nf_min", 1)),
        "nf_max": int(policy.get("nf_max", 1)),
    }


def _linspace(minimum: float, maximum: float, count: int) -> list[float]:
    if count <= 0:
        raise GenericStep5Error("continuous sample count must be positive")
    if count == 1:
        return [0.5 * (minimum + maximum)]
    step = (maximum - minimum) / (count - 1)
    return [minimum + index * step for index in range(count)]


def enumerate_independent_domains(
    artifact: Mapping[str, Any],
    *,
    continuous_samples: Mapping[str, int],
    range_overrides: Mapping[str, tuple[float, float]],
) -> tuple[list[str], list[tuple[float, ...]], dict[str, list[float]]]:
    names: list[str] = []
    values_by_name: dict[str, list[float]] = {}
    for name, domain in artifact["domains"].items():
        candidates = [float(value) for value in domain.get("candidate_values", [])]
        if candidates:
            values = candidates
        else:
            minimum = float(domain["technology_minimum"])
            maximum = float(domain["technology_maximum"])
            if name in range_overrides:
                requested_minimum, requested_maximum = range_overrides[name]
                minimum = max(minimum, requested_minimum)
                maximum = min(maximum, requested_maximum)
            if minimum > maximum:
                raise GenericStep5Error(f"empty overridden range for {name!r}")
            sample_count = continuous_samples.get(name)
            if sample_count is None:
                embedded_count = domain.get("sample_count")
                if embedded_count is not None:
                    sample_count = int(embedded_count)
            if sample_count is None:
                raise GenericStep5Error(
                    f"continuous independent variable {name!r} requires an explicit sample count"
                )
            values = _linspace(minimum, maximum, sample_count)
        names.append(name)
        values_by_name[name] = values
    combinations = list(itertools.product(*(values_by_name[name] for name in names)))
    return names, combinations, values_by_name


def _eval_expression(expression: str, values: Mapping[str, float]) -> float:
    rewritten = CURRENT_TOKEN_RE.sub(lambda match: f"i_{match.group(1).lower()}_a", expression)
    tree = ast.parse(rewritten, mode="eval")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise KeyError(node.id)
            return float(values[node.id])
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return -value
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        raise GenericStep5Error(f"unsupported expression node {type(node).__name__}")

    return visit(tree)



def _evaluate_dc_propagation_diagnostics(
    model: Mapping[str, Any],
    values: Mapping[str, float],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate designer-authored DC propagation operations diagnostically.

    These results do not affect assignment acceptance yet.
    """

    propagation = (
        model.get("synthesis_interface", {})
        .get("dc_propagation", {})
        or {}
    )
    operations = propagation.get("operations", []) or []

    scope: dict[str, float] = {
        str(key): float(value)
        for key, value in values.items()
        if isinstance(value, (int, float))
    }

    operating = (
        model["project_inputs"]["design_rules"]
        .get("operating_conditions", {})
    )
    scope.update(
        {
            str(key): float(value)
            for key, value in operating.items()
            if isinstance(value, (int, float))
        }
    )

    for raw_device, item in provenance.items():
        if not isinstance(item, Mapping):
            continue

        vdsat = item.get("vdsat_v")
        if vdsat is None:
            continue

        device = str(raw_device).lower()
        value = float(vdsat)

        scope[f"vdsat_{device}"] = value
        scope[f"vdsat_{device}_v"] = value

    results: dict[str, Any] = {}

    for operation in operations:
        operation_id = str(operation.get("id", ""))
        operation_type = str(operation.get("type", ""))
        target = str(operation.get("target", ""))
        expression = operation.get("expression")

        record: dict[str, Any] = {
            "type": operation_type,
            "target": target,
            "expression": expression,
            "status": "not_evaluated",
        }

        if operation_type not in {
            "equation",
            "lower_bound",
            "upper_bound",
        }:
            record["status"] = "unsupported_operation_type"
            results[operation_id] = record
            continue

        if not isinstance(expression, str) or not expression.strip():
            record["status"] = "missing_expression"
            results[operation_id] = record
            continue

        try:
            value = _eval_expression(expression, scope)
        except KeyError as exc:
            record["status"] = "missing_variable"
            record["missing_variable"] = str(exc.args[0])
        except GenericStep5Error as exc:
            record["status"] = "evaluation_error"
            record["error"] = str(exc)
        else:
            record["status"] = "evaluated"
            record["value"] = float(value)

        results[operation_id] = record

    evaluated_values = [
        float(record["value"])
        for record in results.values()
        if record.get("status") == "evaluated"
    ]

    return {
        "mode": "diagnostic_only",
        "authoritative": False,
        "operation_count": len(operations),
        "evaluated_count": len(evaluated_values),
        "operations": results,
    }


def _current_variable(token: str) -> str | None:
    """Return the canonical assignment variable for a current reference."""

    stripped = token.strip()
    device_match = CURRENT_TOKEN_RE.fullmatch(stripped)
    if device_match:
        return f"i_{device_match.group(1).lower()}_a"
    if re.fullmatch(r"i_[A-Za-z_][A-Za-z0-9_]*_a", stripped):
        return stripped.lower()
    return None


def propagate_compiled_equations(model: Mapping[str, Any], values: dict[str, float]) -> None:
    """Propagate compiled current equations without rejecting unresolved aliases.

    Equations whose right side is evaluable are propagated normally.  A pure
    current alias, such as ``i_m6_a = device.M7.current``, is also propagated
    in the reverse direction when the left side is already known.  When both
    sides of a pure alias are still dependent, the relation is deferred to the
    correlated device-group join rather than rejecting the independent point.
    """

    pending: list[tuple[str, str]] = []
    for item in model["constraint_model"].get("canonical_constraints", []):
        expression = str(item["expression"])
        separator = "==" if "==" in expression else "=" if "=" in expression else None
        if separator is None:
            continue
        left_text, right_text = expression.split(separator, 1)
        left = _current_variable(left_text)
        if left is not None:
            pending.append((left, right_text.strip()))

    while pending:
        next_pending: list[tuple[str, str]] = []
        progress = False

        for left, right in pending:
            right_alias = _current_variable(right)

            try:
                result = _eval_expression(right, values)
            except KeyError:
                result = None

            if result is not None:
                if result <= 0.0:
                    raise GenericStep5Error(
                        f"derived non-positive current {left}={result}"
                    )
                existing = values.get(left)
                if existing is not None and not math.isclose(
                    float(existing), result, rel_tol=1e-9, abs_tol=1e-15
                ):
                    raise GenericStep5Error(
                        f"conflicting current equation {left}: {existing} != {result}"
                    )
                if existing is None:
                    values[left] = result
                    progress = True
                continue

            if right_alias is not None and left in values and right_alias not in values:
                value = float(values[left])
                if value <= 0.0:
                    raise GenericStep5Error(
                        f"derived non-positive current {right_alias}={value}"
                    )
                values[right_alias] = value
                progress = True
                continue

            next_pending.append((left, right))

        if not next_pending:
            return
        if not progress:
            non_alias = [item for item in next_pending if _current_variable(item[1]) is None]
            if non_alias:
                raise GenericStep5Error(
                    f"unresolved current equations: {non_alias!r}"
                )
            # Pure dependent-current aliases are enforced by the correlated
            # group candidates later in Step 5 and are not independent-point
            # propagation failures.
            return
        pending = next_pending


def _matched_width_groups(model: Mapping[str, Any]) -> list[list[str]]:
    patterns = (
        model["project_inputs"]["design_intent"]
        .get("circuit_intent", {})
        .get("confirmed_patterns", {})
    )
    return [[str(item).upper() for item in group] for group in patterns.get("matched_width_groups", [])]


def _operating_node_values(model: Mapping[str, Any], values: Mapping[str, float]) -> dict[str, float]:
    operating = model["project_inputs"]["design_rules"].get("operating_conditions", {})
    nodes: dict[str, float] = {}
    aliases = {
        "vdd": ("vdd_v", "vdd"),
        "vss": ("vss_v", "vss"),
        "vip": ("vin_cm_v", "input_common_mode_v", "input_common_mode"),
        "vin": ("vin_cm_v", "input_common_mode_v", "input_common_mode"),
        "inp": ("vin_cm_v", "input_common_mode_v", "input_common_mode"),
        "inn": ("vin_cm_v", "input_common_mode_v", "input_common_mode"),
    }
    for node, keys in aliases.items():
        for key in keys:
            if key in operating:
                nodes[node] = float(operating[key])
                break
    for key, value in values.items():
        if not key.endswith("_v"):
            continue
        token = key[:-2]
        nodes[token] = float(value)
        if token.startswith("v") and len(token) > 1:
            nodes.setdefault(token[1:], float(value))
        nodes.setdefault(f"{token}_node", float(value))
    return nodes


def _known_device_voltages(
    device: Mapping[str, Any], polarity: str, nodes: Mapping[str, float]
) -> tuple[float | None, float | None, float | None]:
    terminals = device.get("terminals", {})
    vd = nodes.get(str(terminals.get("drain", "")).lower())
    vg = nodes.get(str(terminals.get("gate", "")).lower())
    vs = nodes.get(str(terminals.get("source", "")).lower())
    vb = nodes.get(str(terminals.get("bulk", "")).lower())
    vgs = None if vg is None or vs is None else (vg - vs if polarity == "nmos" else vs - vg)
    vds = None if vd is None or vs is None else (vd - vs if polarity == "nmos" else vs - vd)
    vbs = None if vb is None or vs is None else abs(vb - vs)
    return vgs, vds, vbs


def _apply_realization_to_nodes(
    device: Mapping[str, Any],
    polarity: str,
    realization: DeviceRealization,
    nodes: dict[str, float],
    tolerance: float,
) -> bool:
    """Apply exact VGS/VBS relations and feasible saturated-VDS bounds.

    The MOS bulk terminal is fixed by the extracted topology.  For the usual
    OpenAMS connection policy, NMOS bulks are tied to VSS and PMOS bulks are
    tied to VDD.  Therefore VBS is never an independent technology choice:
    the selected inverse-feasible row must agree with the circuit source and
    bulk nodes, or it may derive the missing source node from the known bulk.

    VGS and |VBS| are equality constraints.  VDS remains a feasible interval
    and must never be used to invent an exact drain voltage.
    """

    terminals = {
        key: str(value).lower()
        for key, value in device.get("terminals", {}).items()
    }
    required = {"drain", "gate", "source", "bulk"}
    missing = required - set(terminals)
    if missing:
        raise GenericStep5Error(
            f"device {device.get('name', '<unknown>')!r} is missing MOS terminals: "
            f"{sorted(missing)!r}"
        )

    gate = terminals["gate"]
    drain = terminals["drain"]
    source = terminals["source"]
    bulk = terminals["bulk"]

    # First enforce the body/source relation.  The characterization tables use
    # an absolute body-bias magnitude.  With NMOS bulk at the low rail, the
    # source is bulk + |VBS|.  With PMOS bulk at the high rail, the source is
    # bulk - |VBS|.
    bulk_value = nodes.get(bulk)
    source_value = nodes.get(source)
    requested_vbs = abs(float(realization.vbs_v))

    if bulk_value is not None and source_value is not None:
        actual_vbs = abs(bulk_value - source_value)
        if abs(actual_vbs - requested_vbs) > tolerance:
            return False
    elif bulk_value is not None:
        if polarity == "nmos":
            nodes[source] = bulk_value + requested_vbs
        else:
            nodes[source] = bulk_value - requested_vbs
    elif source_value is not None:
        if polarity == "nmos":
            nodes[bulk] = source_value - requested_vbs
        else:
            nodes[bulk] = source_value + requested_vbs

    # Re-read the source after VBS propagation before applying VGS.
    source_value = nodes.get(source)
    gate_value = nodes.get(gate)

    if polarity == "nmos":
        positive, negative = gate, source
    else:
        positive, negative = source, gate

    positive_value = nodes.get(positive)
    negative_value = nodes.get(negative)
    if positive_value is not None and negative_value is not None:
        if abs((positive_value - negative_value) - realization.vgs_v) > tolerance:
            return False
    elif positive_value is not None:
        nodes[negative] = positive_value - realization.vgs_v
    elif negative_value is not None:
        nodes[positive] = negative_value + realization.vgs_v

    # Validate the derived source/bulk relation once more in case VGS
    # propagation established a source node that was previously unknown.
    bulk_value = nodes.get(bulk)
    source_value = nodes.get(source)
    if bulk_value is not None and source_value is not None:
        actual_vbs = abs(bulk_value - source_value)
        if abs(actual_vbs - requested_vbs) > tolerance:
            return False

    # VDS is an interval constraint, not an equality.  Only check it when both
    # terminal voltages are known.
    if polarity == "nmos":
        vds_positive, vds_negative = drain, source
    else:
        vds_positive, vds_negative = source, drain

    drain_value = nodes.get(vds_positive)
    source_for_vds = nodes.get(vds_negative)
    minimum_vds = float(
        realization.provenance.get(
            "minimum_saturated_vds_v",
            realization.vds_v,
        )
    )
    maximum_vds_raw = realization.provenance.get(
        "maximum_characterized_vds_v"
    )
    maximum_vds = (
        float(maximum_vds_raw)
        if maximum_vds_raw is not None
        else None
    )

    if drain_value is not None and source_for_vds is not None:
        actual_vds = drain_value - source_for_vds
        if actual_vds + tolerance < minimum_vds:
            return False
        if maximum_vds is not None and actual_vds - tolerance > maximum_vds:
            return False

    return True


def _group_order(
    model: Mapping[str, Any],
    groups: Sequence[Sequence[str]],
    independent_ids: set[str],
) -> list[list[str]]:
    """Order groups by how strongly the independent variables constrain them."""

    devices = _device_map(model)
    operating_nodes = set(_operating_node_values(model, {}).keys())

    def score(group: Sequence[str]) -> tuple[int, int, str]:
        fixed_width = any(f"w_{member.lower()}_um" in independent_ids for member in group)
        connected_known = 0
        for member in group:
            terminals = devices[member].get("terminals", {})
            connected_known += sum(str(node).lower() in operating_nodes for node in terminals.values())
        return (0 if fixed_width else 1, -connected_known, ",".join(group))

    return [list(group) for group in sorted(groups, key=score)]




def _candidate_value_from_state(
    key: str,
    values: Mapping[str, float],
    nodes: Mapping[str, float],
) -> float | None:
    if key in values:
        return float(values[key])
    if key.endswith("_v") and key[:-2] in nodes:
        return float(nodes[key[:-2]])
    return None


def _correlated_candidate_expansions(
    dependency_plan: Mapping[str, Any],
    values: Mapping[str, float],
    nodes: Mapping[str, float],
    required_keys: set[str],
    *,
    voltage_tolerance_v: float,
    relative_tolerance: float = 1e-9,
    absolute_tolerance: float = 1e-12,
) -> list[tuple[dict[str, float], dict[str, float], str]]:
    """Return atomic correlated-candidate joins that can supply missing keys.

    This is topology-neutral: any dependency-plan group may expose a list of
    ``correlated_candidates``.  A candidate is eligible when it produces at
    least one required key and all values already known in the search state
    agree within tolerance.
    """

    expansions: list[tuple[dict[str, float], dict[str, float], str]] = []
    for group in dependency_plan.get("groups", []):
        candidates = group.get("correlated_candidates")
        if not isinstance(candidates, list) or not candidates:
            continue
        produced = set()
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                produced.update(str(key) for key in candidate)
        if not (required_keys & produced):
            continue

        group_id = str(group.get("group_id", "correlated_candidates"))
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            compatible = True
            for raw_key, raw_value in candidate.items():
                key = str(raw_key)
                try:
                    candidate_value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                known = _candidate_value_from_state(key, values, nodes)
                if known is None:
                    continue
                tolerance = voltage_tolerance_v if key.endswith("_v") else absolute_tolerance
                if not math.isclose(known, candidate_value, rel_tol=relative_tolerance, abs_tol=tolerance):
                    compatible = False
                    break
            if not compatible:
                continue

            next_values = dict(values)
            next_nodes = dict(nodes)
            conflict = False
            for raw_key, raw_value in candidate.items():
                key = str(raw_key)
                try:
                    candidate_value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                known = _candidate_value_from_state(key, next_values, next_nodes)
                tolerance = voltage_tolerance_v if key.endswith("_v") else absolute_tolerance
                if known is not None and not math.isclose(
                    known, candidate_value, rel_tol=relative_tolerance, abs_tol=tolerance
                ):
                    conflict = True
                    break
                next_values[key] = candidate_value
                if key.endswith("_v"):
                    next_nodes[key[:-2]] = candidate_value
            if not conflict:
                expansions.append((next_values, next_nodes, group_id))
    return expansions


def _group_choices(
    model: Mapping[str, Any],
    provider: DeviceProvider,
    group: Sequence[str],
    values: Mapping[str, float],
    nodes: Mapping[str, float],
    independent_ids: set[str],
    *,
    max_device_candidates: int,
    max_group_choices: int,
) -> tuple[Iterator[tuple[dict[str, DeviceRealization], dict[str, float]]], str | None]:
    devices = _device_map(model)
    width_policy = _width_policy(model)
    rules = model["project_inputs"]["design_rules"]
    all_mos = rules["device_constraints"]["all_mos"]
    intersection = rules.get("technology_intersection", {})
    current_rel = float(intersection.get("current_relative_tolerance", 0.1))
    current_abs = float(intersection.get("current_absolute_tolerance_a", 1e-6))
    voltage_tol = float(intersection.get("node_voltage_tolerance_v", 0.025))

    fixed_widths = {
        float(values[f"w_{member.lower()}_um"])
        for member in group
        if f"w_{member.lower()}_um" in independent_ids and f"w_{member.lower()}_um" in values
    }
    if len(fixed_widths) > 1:
        return iter(()), f"MATCHED_WIDTH_CONFLICT:{list(group)}"
    fixed_width = next(iter(fixed_widths)) if fixed_widths else None

    candidate_lists: dict[str, Sequence[DeviceRealization]] = {}
    for member in group:
        device = devices[member]
        polarity = _polarity(str(device["model"]))
        known_vgs, known_vds, known_vbs = _known_device_voltages(device, polarity, nodes)
        terminals = {
            key: str(value).lower()
            for key, value in device.get("terminals", {}).items()
        }

        request = DeviceRequest(
            device=member,
            model=str(device["model"]),
            polarity=polarity,
            length_um=float(all_mos["length_um"]),
            target_current_a=float(values[f"i_{member.lower()}_a"]),
            fixed_width_um=fixed_width,
            known_vgs_v=known_vgs,
            known_vds_v=known_vds,
            known_vbs_v=known_vbs,
            known_gate_v=nodes.get(terminals.get("gate", "")),
            known_drain_v=nodes.get(terminals.get("drain", "")),
            known_source_v=nodes.get(terminals.get("source", "")),
            known_bulk_v=nodes.get(terminals.get("bulk", "")),
            require_saturation=True,
        )

        # Optional provider-request tracing for one-point regression debugging.
        # Disabled by default so production search behavior and performance are
        # unchanged. Enable with OPENAMS_DEBUG_DEVICE_REQUESTS=1. Restrict the
        # printed devices with OPENAMS_DEBUG_DEVICE_FILTER=M1,M2,M3,M4,M5.
        if os.environ.get("OPENAMS_DEBUG_DEVICE_REQUESTS", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            configured = os.environ.get(
                "OPENAMS_DEBUG_DEVICE_FILTER",
                "M1,M2,M3,M4,M5",
            )
            debug_devices = {
                token.strip().upper()
                for token in configured.split(",")
                if token.strip()
            }
            if not debug_devices or member.upper() in debug_devices:
                print(
                    "DEVICE_REQUEST",
                    json.dumps(
                        {
                            "device": member,
                            "target_current_a": request.target_current_a,
                            "fixed_width_um": request.fixed_width_um,
                            "known_vgs_v": request.known_vgs_v,
                            "known_vds_v": request.known_vds_v,
                            "known_vbs_v": request.known_vbs_v,
                            "nodes": {
                                str(key): float(value)
                                for key, value in sorted(nodes.items())
                            },
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

        candidates = provider.candidates(
            request,
            current_relative_tolerance=current_rel,
            current_absolute_tolerance_a=current_abs,
            voltage_tolerance_v=voltage_tol,
            width_policy=width_policy,
            limit=max_device_candidates,
        )
        if not candidates:
            return iter(()), f"NO_DEVICE_REALIZATION:{member}"
        candidate_lists[member] = candidates

    width_sets = [
        {round(item.width_um, 9) for item in candidate_lists[member]}
        for member in group
    ]
    common_widths = set.intersection(*width_sets) if width_sets else set()
    if fixed_width is not None:
        common_widths = {round(fixed_width, 9)} & common_widths
    if not common_widths:
        return iter(()), f"NO_MATCHED_GROUP_JOIN:{list(group)}"

    def iter_choices() -> Iterator[tuple[dict[str, DeviceRealization], dict[str, float]]]:
        emitted = 0
        for width_token in sorted(common_widths):
            per_member = [
                [item for item in candidate_lists[member] if round(item.width_um, 9) == width_token]
                for member in group
            ]
            for combination in itertools.product(*per_member):
                trial_nodes = dict(nodes)
                selection: dict[str, DeviceRealization] = {}
                valid = True
                for member, realization in zip(group, combination, strict=True):
                    polarity = _polarity(str(devices[member]["model"]))
                    if not _apply_realization_to_nodes(
                        devices[member], polarity, realization, trial_nodes, voltage_tol
                    ):
                        valid = False
                        break
                    selection[member] = realization
                if not valid:
                    continue
                yield selection, trial_nodes
                emitted += 1
                if emitted >= max_group_choices:
                    return

    return iter_choices(), None

def _declarative_headroom_valid(
    model: Mapping[str, Any],
    values: MutableMapping[str, float],
    provenance: Mapping[str, Any],
) -> bool:
    """Validate or derive the legal output-voltage window.

    Metadata may declare ``vout_v`` as an independent scalar. In that case
    the exact value is checked against the derived headroom window. Metadata
    may instead declare only lower and upper headroom expressions; Step 5 then
    retains the feasible interval without inventing an exact output voltage.
    """

    specifications = model["project_inputs"]["specifications"]
    dc_validity = specifications.get("dc_validity", {})
    headroom = dc_validity.get("topology_headroom")

    # Generic compiled models may place output-headroom constraints under
    # design_rules.circuit_constraints rather than specifications.dc_validity.
    if not headroom:
        headroom = (
            model["project_inputs"]["design_rules"]
            .get("circuit_constraints", {})
            .get("output_headroom")
        )

    if not headroom:
        return True

    scope: dict[str, float] = dict(values)
    operating = model["project_inputs"]["design_rules"].get(
        "operating_conditions", {}
    )
    scope.update(
        {
            key: float(value)
            for key, value in operating.items()
            if isinstance(value, (int, float))
        }
    )
    for device, item in provenance.items():
        vdsat = item.get("vdsat_v")
        if vdsat is not None:
            device_name = device.lower()
            value = float(vdsat)
            # Support both historical and compiled-schema variable names.
            scope[f"vdsat_{device_name}"] = value
            scope[f"vdsat_{device_name}_v"] = value

    def simple(expr: str) -> float:
        tree = ast.parse(expr, mode="eval")

        def visit(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant):
                return float(node.value)
            if isinstance(node, ast.Name):
                aliases = {
                    "vdd": "vdd_v",
                    "vss": "vss_v",
                    "vout": "vout_v",
                }
                key = aliases.get(node.id, node.id)
                if key not in scope:
                    raise KeyError(key)
                return float(scope[key])
            if isinstance(node, ast.BinOp):
                left = visit(node.left)
                right = visit(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
            raise GenericStep5Error("unsupported headroom expression")

        return visit(tree)

    def normalized_bound(raw: Any, comparison: str) -> str:
        if isinstance(raw, Mapping):
            raw = raw.get("equation")
        if raw is None:
            raise KeyError("missing headroom bound")

        expression = str(raw).strip()
        if comparison in expression:
            expression = expression.split(comparison, 1)[1].strip()
        return expression

    try:
        lower_expression = normalized_bound(headroom["lower_bound"], ">")
        upper_expression = normalized_bound(headroom["upper_bound"], "<")
        lower = simple(lower_expression)
        upper = simple(upper_expression)
    except (KeyError, TypeError, ValueError, SyntaxError):
        return False

    # Intersect topology headroom with any declared output specification.
    output_spec = dc_validity.get("output_voltage", {})
    spec_min = output_spec.get("min")
    spec_max = output_spec.get("max")
    if isinstance(spec_min, (int, float)):
        lower = max(lower, float(spec_min))
    if isinstance(spec_max, (int, float)):
        upper = min(upper, float(spec_max))

    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        return False

    values["vout_min_v"] = lower
    values["vout_max_v"] = upper

    # Only validate an exact Vout when the circuit actually supplied one.
    if "vout_v" in values:
        try:
            vout = float(values["vout_v"])
        except (TypeError, ValueError):
            return False
        return lower < vout < upper

    return True




def _intersect_output_device_windows(
    model: Mapping[str, Any],
    values: MutableMapping[str, float],
    nodes: Mapping[str, float],
    provenance: Mapping[str, Any],
) -> bool:
    """Intersect VOUT intervals implied by output-connected MOS devices."""

    devices = _device_map(model)
    tolerance = float(
        model["project_inputs"]["design_rules"]
        .get("technology_intersection", {})
        .get("node_voltage_tolerance_v", 0.025)
    )

    output_nodes: set[str] = {"out", "vout"}
    topology = model.get("topology", {})
    for port in topology.get("ports", []):
        if isinstance(port, str):
            token = port.lower()
            if token in {"out", "vout"}:
                output_nodes.add(token)
        elif isinstance(port, Mapping):
            name = str(port.get("name", port.get("id", port.get("node", "")))).lower()
            direction = str(port.get("direction", port.get("role", ""))).lower()
            if name and (name in {"out", "vout"} or direction == "output" or "output" in direction):
                output_nodes.add(name)

    lower = float(values.get("vout_min_v", -math.inf))
    upper = float(values.get("vout_max_v", math.inf))
    constrained = False

    for member, item in provenance.items():
        device = devices.get(str(member).upper())
        if device is None:
            continue

        terminals = {key: str(value).lower() for key, value in device.get("terminals", {}).items()}
        drain = terminals.get("drain", "")
        source = terminals.get("source", "")
        if drain not in output_nodes:
            continue

        source_value = nodes.get(source)
        if source_value is None:
            return False

        minimum_vds = float(item.get("minimum_saturated_vds_v", item.get("vds_v", 0.0)))
        maximum_vds_raw = item.get("maximum_characterized_vds_v")
        maximum_vds = float(maximum_vds_raw) if maximum_vds_raw is not None else None
        polarity = _polarity(str(device["model"]))

        if polarity == "nmos":
            device_lower = source_value + minimum_vds
            device_upper = source_value + maximum_vds if maximum_vds is not None else math.inf
        else:
            device_lower = source_value - maximum_vds if maximum_vds is not None else -math.inf
            device_upper = source_value - minimum_vds

        lower = max(lower, device_lower)
        upper = min(upper, device_upper)
        constrained = True

        if lower + tolerance >= upper:
            return False

    if constrained:
        values["vout_min_v"] = lower
        values["vout_max_v"] = upper

    return (
        math.isfinite(float(values.get("vout_min_v", lower)))
        and math.isfinite(float(values.get("vout_max_v", upper)))
        and float(values.get("vout_min_v", lower)) < float(values.get("vout_max_v", upper))
    )

def _final_selected_device_failures(
    model: Mapping[str, Any],
    nodes: Mapping[str, float],
    provenance: Mapping[str, Any],
) -> list[str]:
    """Globally revalidate selected MOS devices at a completed search branch.

    A device with an unresolved drain, normally because it connects to a
    ranged VOUT node, remains deferred rather than being rejected here.
    """

    devices = _device_map(model)
    intersection = (
        model["project_inputs"]["design_rules"]
        .get("technology_intersection", {})
    )
    tolerance = float(
        intersection.get("node_voltage_tolerance_v", 0.025)
    )
    failures: list[str] = []

    for member, item in provenance.items():
        device = devices.get(str(member).upper())
        if device is None:
            failures.append(f"FINAL_UNKNOWN_DEVICE:{member}")
            continue

        polarity = _polarity(str(device["model"]))
        terminals = {
            key: str(value).lower()
            for key, value in device.get("terminals", {}).items()
        }

        vd = nodes.get(terminals.get("drain", ""))
        vg = nodes.get(terminals.get("gate", ""))
        vs = nodes.get(terminals.get("source", ""))
        vb = nodes.get(terminals.get("bulk", ""))

        expected_vgs = item.get("vgs_v")
        expected_vbs = item.get("vbs_v")

        if vg is not None and vs is not None and expected_vgs is not None:
            actual_vgs = (
                vg - vs if polarity == "nmos" else vs - vg
            )
            if abs(actual_vgs - float(expected_vgs)) > tolerance:
                failures.append(f"FINAL_VGS_MISMATCH:{member}")

        if vb is not None and vs is not None and expected_vbs is not None:
            actual_vbs = abs(vb - vs)
            if abs(actual_vbs - abs(float(expected_vbs))) > tolerance:
                failures.append(f"FINAL_VBS_MISMATCH:{member}")

        # A ranged output node may leave VD unresolved. Do not reject it here.
        if vd is None or vs is None:
            continue

        actual_vds = vd - vs if polarity == "nmos" else vs - vd
        minimum_vds = float(
            item.get(
                "minimum_saturated_vds_v",
                item.get("vds_v", 0.0),
            )
        )
        maximum_vds_raw = item.get("maximum_characterized_vds_v")
        maximum_vds = (
            float(maximum_vds_raw)
            if maximum_vds_raw is not None
            else None
        )
        vdsat_raw = item.get("vdsat_v")
        vdsat = float(vdsat_raw) if vdsat_raw is not None else None

        if actual_vds + tolerance < minimum_vds:
            failures.append(
                f"FINAL_VDS_BELOW_MIN:{member}:"
                f"actual={actual_vds:.6f}:"
                f"min_supported={minimum_vds:.6f}:"
                f"vdsat={vdsat if vdsat is not None else 'none'}:"
                f"drain={vd:.6f}:source={vs:.6f}"
            )
            continue

        if maximum_vds is not None and actual_vds - tolerance > maximum_vds:
            failures.append(
                f"FINAL_VDS_ABOVE_MAX:{member}:"
                f"actual={actual_vds:.6f}:"
                f"max_supported={maximum_vds:.6f}:"
                f"vdsat={vdsat if vdsat is not None else 'none'}:"
                f"drain={vd:.6f}:source={vs:.6f}"
            )
            continue

        if vdsat is not None and actual_vds + tolerance < vdsat:
            failures.append(f"FINAL_NOT_SATURATED:{member}")

    return failures

def _solve_all_independent_point(
    model: Mapping[str, Any],
    provider: DeviceProvider,
    independent_values: Mapping[str, float],
    *,
    dependency_plan: Mapping[str, Any] | None = None,
    max_device_candidates: int,
    max_group_choices: int = 64,
    max_solutions: int = 64,
    search_profile: SearchProfile | None = None,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    values = {str(key): float(value) for key, value in independent_values.items()}
    failures: Counter[str] = Counter()
    profile = search_profile if search_profile is not None else SearchProfile()
    try:
        propagate_compiled_equations(model, values)
    except GenericStep5Error as exc:
        reason = f"EQUATION_PROPAGATION:{exc}"
        failures[reason] += 1
        profile.record_rejection(reason)
        return [], failures

    devices = _device_map(model)
    matched = _matched_width_groups(model)
    group_for = {member: group for group in matched for member in group}
    raw_groups: list[tuple[str, ...]] = []
    for device in sorted(devices):
        key = tuple(group_for.get(device, [device]))
        if key not in raw_groups:
            raw_groups.append(key)
    independent_ids = {
        str(item["id"])
        for item in model.get("synthesis_interface", {}).get("independent_variables", [])
    }
    groups = _group_order(model, raw_groups, independent_ids)
    starting_nodes = _operating_node_values(model, values)
    solutions: list[dict[str, Any]] = []
    seen_exact_states: set[tuple[Any, ...]] = set()
    seen_branch_states: set[tuple[Any, ...]] = set()

    def visit(state: SearchState) -> None:
        profile.recursion_nodes += 1
        exact_key = state.exact_key()
        if exact_key in seen_exact_states:
            profile.repeated_exact_states_observed += 1
        else:
            seen_exact_states.add(exact_key)
            profile.unique_exact_states += 1

        branch_key = _branch_key(state)
        if branch_key in seen_branch_states:
            profile.pruned_branch_states += 1
            return
        seen_branch_states.add(branch_key)
        profile.max_depth = max(profile.max_depth, state.group_index)
        if len(solutions) >= max_solutions:
            profile.solution_limit_hits += 1
            return
        if state.group_index >= len(groups):
            profile.terminal_states += 1
            final_values = dict(state.values)
            for node, value in state.nodes.items():
                final_values.setdefault(f"{node}_v", value)

            final_device_failures = _final_selected_device_failures(
                model,
                state.nodes,
                state.provenance,
            )
            if final_device_failures:
                failures.update(final_device_failures)
                profile.rejection_counts.update(final_device_failures)
                return

            if not _declarative_headroom_valid(model, final_values, state.provenance):
                failures["HEADROOM_CONSTRAINT"] += 1
                profile.record_rejection("HEADROOM_CONSTRAINT")
                return

            if not _intersect_output_device_windows(
                model,
                final_values,
                state.nodes,
                state.provenance,
            ):
                failures["OUTPUT_DEVICE_WINDOW_EMPTY"] += 1
                profile.record_rejection("OUTPUT_DEVICE_WINDOW_EMPTY")
                return

            exact_vout = "vout_v" in final_values
            region = OperatingRegion(
                values=final_values,
                device_technology_provenance=dict(state.provenance),
                assignment_semantics=(
                    "model_valid_dc_operating_point"
                    if exact_vout
                    else "model_valid_dc_operating_region"
                ),
                physical_proof_level=(
                    "inverse_feasible_dataset_and_compiled_constraint_valid"
                ),
                route=(
                    "ngspice_dc_confirmation"
                    if exact_vout
                    else "select_vout_within_feasible_window"
                ),
            )
            assignment = region.to_assignment()
            assignment["dc_propagation_diagnostics"] = (
                _evaluate_dc_propagation_diagnostics(
                    model,
                    final_values,
                    state.provenance,
                )
            )
            solutions.append(assignment)
            profile.accepted_solutions += 1
            return

        group = groups[state.group_index]
        group_name = ",".join(group)
        profile.group_calls[group_name] += 1

        missing_current_keys = {
            f"i_{member.lower()}_a"
            for member in group
            if f"i_{member.lower()}_a" not in state.values
        }
        if missing_current_keys and dependency_plan is not None:
            voltage_tol = float(
                model["project_inputs"]["design_rules"]
                .get("technology_intersection", {})
                .get("node_voltage_tolerance_v", 0.025)
            )
            expansions = _correlated_candidate_expansions(
                dependency_plan,
                state.values,
                state.nodes,
                missing_current_keys,
                voltage_tolerance_v=voltage_tol,
            )
            if expansions:
                for expanded_values, expanded_nodes, group_id in expansions:
                    if len(solutions) >= max_solutions:
                        break
                    try:
                        propagate_compiled_equations(model, expanded_values)
                    except GenericStep5Error as exc:
                        reason = f"EQUATION_PROPAGATION_AFTER_CANDIDATE:{group_id}:{exc}"
                        failures[reason] += 1
                        profile.record_rejection(reason)
                        continue
                    visit(
                        SearchState(
                            group_index=state.group_index,
                            values=expanded_values,
                            nodes=expanded_nodes,
                            provenance=dict(state.provenance),
                        )
                    )
                return

        if missing_current_keys:
            reason = f"GROUP_NOT_READY:{group_name}:{sorted(missing_current_keys)}"
            failures[reason] += 1
            profile.group_empty[group_name] += 1
            profile.record_rejection(reason)
            return

        choices, failure = _group_choices(
            model,
            provider,
            group,
            state.values,
            state.nodes,
            independent_ids,
            max_device_candidates=max_device_candidates,
            max_group_choices=max_group_choices,
        )
        if failure is not None:
            reason = str(failure)
            failures[reason] += 1
            profile.group_empty[group_name] += 1
            profile.record_rejection(reason)
            return

        choice_count = 0
        for selection, trial_nodes in choices:
            if len(solutions) >= max_solutions:
                break
            choice_count += 1
            profile.group_choices[group_name] += 1
            next_values = dict(state.values)
            next_provenance = dict(state.provenance)
            for member, realization in selection.items():
                width_key = f"w_{member.lower()}_um"
                if width_key in independent_ids and not math.isclose(
                    next_values[width_key], realization.width_um, rel_tol=1e-6, abs_tol=1e-9
                ):
                    reason = f"INDEPENDENT_WIDTH_OVERWRITE:{member}"
                    failures[reason] += 1
                    profile.record_rejection(reason)
                    break
                next_values[width_key] = realization.width_um
                next_values[f"nf_{member.lower()}"] = float(realization.nf)
                next_values[f"w_finger_{member.lower()}_um"] = realization.finger_width_um
                next_provenance[member] = {
                    **dict(realization.provenance),
                    "provider": provider.name,
                    "width_um": realization.width_um,
                    "nf": realization.nf,
                    "finger_width_um": realization.finger_width_um,
                    "predicted_current_a": realization.predicted_current_a,
                    "vgs_v": realization.vgs_v,
                    "minimum_saturated_vds_v": realization.provenance.get(
                        "minimum_saturated_vds_v", realization.vds_v
                    ),
                    "maximum_characterized_vds_v": realization.provenance.get(
                        "maximum_characterized_vds_v"
                    ),
                    "vbs_v": realization.vbs_v,
                    "vdsat_v": realization.vdsat_v,
                    "saturated": realization.saturated,
                }
            else:
                visit(
                    SearchState(
                        group_index=state.group_index + 1,
                        values=next_values,
                        nodes=dict(trial_nodes),
                        provenance=next_provenance,
                    )
                )

        if choice_count == 0:
            reason = f"NO_MATCHED_GROUP_JOIN:{list(group)}"
            failures[reason] += 1
            profile.group_empty[group_name] += 1
            profile.record_rejection(reason)

    visit(
        SearchState(
            group_index=0,
            values=values,
            nodes=starting_nodes,
            provenance={},
        )
    )
    return solutions, failures


def _solve_one_independent_point(
    model: Mapping[str, Any],
    provider: DeviceProvider,
    independent_values: Mapping[str, float],
    *,
    max_device_candidates: int,
) -> tuple[dict[str, Any] | None, str | None]:
    solutions, failures = _solve_all_independent_point(
        model,
        provider,
        independent_values,
        max_device_candidates=max_device_candidates,
        max_solutions=1,
    )
    if solutions:
        return solutions[0], None
    return None, failures.most_common(1)[0][0] if failures else "EMPTY_INTERSECTION"

def build_generic_complete_assignments(
    compiled_model_path: Path,
    independent_regions_path: Path,
    dependent_regions_path: Path,
    *,
    continuous_samples: Mapping[str, int],
    range_overrides: Mapping[str, tuple[float, float]],
    provider_kind: str = "inverse",
    provider_plugin: str | None = None,
    technology_csv_path: Path | None = None,
    enable_mlp_fallback: bool = False,
    adaptive_cache_path: Path | None = None,
    mlp_vgs_count: int = 8,
    mlp_vds_count: int = 10,
    max_device_candidates: int = 64,
    max_group_choices: int = 64,
    max_solutions_per_independent_point: int = 64,
    max_assignments: int | None = None,
) -> Mapping[str, Any]:
    model = json.loads(compiled_model_path.read_text(encoding="utf-8"))

    synthesis_interface = model.get("synthesis_interface", {})
    dc_propagation = synthesis_interface.get("dc_propagation", {}) or {}
    dc_propagation_operations = dc_propagation.get("operations", []) or []

    independent = json.loads(independent_regions_path.read_text(encoding="utf-8"))
    dependency_plan = json.loads(dependent_regions_path.read_text(encoding="utf-8"))
    technology_path = (
        technology_csv_path.resolve()
        if technology_csv_path is not None
        else Path(model["technology"]["source_path"]).resolve()
    )
    if provider_kind == "inverse":
        from openams.synthesis.inverse_feasible_provider import (
            HybridInverseFeasibleProvider,
            InverseFeasibleDatasetProvider,
        )
        margin = float(
            model["project_inputs"]["design_rules"]
            .get("technology_intersection", {})
            .get("saturation_margin_v", 0.0)
        )
        if enable_mlp_fallback:
            import os
            from openams.synthesis.mlp_step5_provider import MlpDeviceProvider
            try:
                nmos_checkpoint = Path(os.environ["OPENAMS_MLP_NMOS"])
                pmos_checkpoint = Path(os.environ["OPENAMS_MLP_PMOS"])
            except KeyError as exc:
                raise GenericStep5Error(
                    "MLP fallback requires OPENAMS_MLP_NMOS and OPENAMS_MLP_PMOS"
                ) from exc
            cache_path = adaptive_cache_path or (
                compiled_model_path.parent / "assignment_synthesis" / "adaptive_inverse_mlp_cache.csv"
            )
            fallback = MlpDeviceProvider(
                nmos_checkpoint=nmos_checkpoint,
                pmos_checkpoint=pmos_checkpoint,
                adaptive_output=cache_path.with_name(cache_path.stem + "_oracle.csv"),
                vgs_count=mlp_vgs_count,
                vds_count=mlp_vds_count,
            )
            provider: DeviceProvider = HybridInverseFeasibleProvider(
                technology_path, fallback_provider=fallback,
                adaptive_cache_path=cache_path, saturation_margin_v=margin
            )
        else:
            provider = InverseFeasibleDatasetProvider(
                technology_path, saturation_margin_v=margin
            )
    elif provider_kind == "table":
        provider = TableDeviceProvider(technology_path)

    elif provider_kind == "mlp":
        import os
        from openams.synthesis.mlp_step5_provider import MlpDeviceProvider

        try:
            nmos_checkpoint = Path(os.environ["OPENAMS_MLP_NMOS"])
            pmos_checkpoint = Path(os.environ["OPENAMS_MLP_PMOS"])
        except KeyError as exc:
            raise GenericStep5Error(
                "MLP provider requires OPENAMS_MLP_NMOS and OPENAMS_MLP_PMOS"
            ) from exc

        oracle_output = adaptive_cache_path or (
            compiled_model_path.parent
            / "assignment_synthesis"
            / "direct_mlp_oracle.csv"
        )

        provider = MlpDeviceProvider(
            nmos_checkpoint=nmos_checkpoint,
            pmos_checkpoint=pmos_checkpoint,
            adaptive_output=oracle_output,
            vgs_count=mlp_vgs_count,
            vds_count=mlp_vds_count,
        )

    elif provider_kind == "plugin" and provider_plugin:
        provider = PluginDeviceProvider(provider_plugin)
    else:
        raise GenericStep5Error(
            "provider must be inverse, table, mlp, or plugin with --provider-plugin"
        )
    names, combinations, values_by_name = enumerate_independent_domains(
        independent,
        continuous_samples=continuous_samples,
        range_overrides=range_overrides,
    )
    assignments: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    aggregate_profile = SearchProfile()
    for combination_index, combination in enumerate(combinations):
        independent_values = dict(zip(names, combination, strict=True))
        point_profile = SearchProfile()
        point_solutions, point_failures = _solve_all_independent_point(
            model,
            provider,
            independent_values,
            dependency_plan=dependency_plan,
            max_device_candidates=max_device_candidates,
            max_group_choices=max_group_choices,
            max_solutions=max_solutions_per_independent_point,
            search_profile=point_profile,
        )
        aggregate_profile.recursion_nodes += point_profile.recursion_nodes
        aggregate_profile.terminal_states += point_profile.terminal_states
        aggregate_profile.accepted_solutions += point_profile.accepted_solutions
        aggregate_profile.max_depth = max(aggregate_profile.max_depth, point_profile.max_depth)
        aggregate_profile.solution_limit_hits += point_profile.solution_limit_hits
        aggregate_profile.group_calls.update(point_profile.group_calls)
        aggregate_profile.group_choices.update(point_profile.group_choices)
        aggregate_profile.group_empty.update(point_profile.group_empty)
        aggregate_profile.rejection_counts.update(point_profile.rejection_counts)
        if not point_solutions:
            rejection_counts.update(point_failures)
            continue
        for local_index, assignment in enumerate(point_solutions):
            assignment["assignment_id"] = f"generic_assignment_{len(assignments):06d}"
            assignment["independent_combination_index"] = combination_index
            assignment["solution_index_within_independent_point"] = local_index
            assignments.append(assignment)
            if max_assignments is not None and len(assignments) >= max_assignments:
                break
        if max_assignments is not None and len(assignments) >= max_assignments:
            break
    flush_provider = getattr(provider, "flush", None)
    if callable(flush_provider):
        flush_provider()
    return {
        "artifact": "openams.complete_dc_assignments",
        "schema_version": 4,
        "status": "PASS" if assignments else "FAIL",
        "circuit_name": model["circuit_name"],
        "algorithm": "generic_independent_grid_device_provider_constraint_join",
        "dc_propagation_plan": {
            "present": bool(dc_propagation),
            "schema_version": dc_propagation.get("schema_version"),
            "execution": dc_propagation.get("execution"),
            "status": dc_propagation.get("status"),
            "operation_count": len(dc_propagation_operations),
            "operation_ids": [
                str(operation.get("id"))
                for operation in dc_propagation_operations
            ],
            "executed": bool(assignments),
            "execution_mode": "diagnostic_only",
            "authoritative": False,
        },
        "device_provider": provider.name,
        "compiled_model": str(compiled_model_path.resolve()),
        "independent_regions": str(independent_regions_path.resolve()),
        "dependent_regions": str(dependent_regions_path.resolve()),
        "technology_source": str(technology_path),
        "independent_variable_names": names,
        "independent_values": values_by_name,
        "independent_combination_count": len(combinations),
        "complete_assignment_count": len(assignments),
        "rejected_combination_count": len(combinations) - len({
            int(item["independent_combination_index"]) for item in assignments
        }),
        "technology_provider_query_count": int(getattr(provider, "query_count", 0)),
        "technology_provider_primary_hit_count": int(getattr(provider, "primary_hit_count", 0)),
        "technology_provider_cache_hit_count": int(getattr(provider, "cache_hit_count", 0)),
        "technology_provider_fallback_request_count": int(getattr(provider, "fallback_request_count", 0)),
        "technology_provider_fallback_query_count": int(getattr(provider, "fallback_query_count", 0)),
        "technology_provider_fallback_result_count": int(getattr(provider, "fallback_result_count", 0)),
        "adaptive_cache_path": (
            str(getattr(provider, "adaptive_cache_path", ""))
            if getattr(provider, "adaptive_cache_path", None) is not None
            else None
        ),
        "fixed_assignment_count": sum(
            item.get("assignment_semantics") == "model_valid_dc_operating_point"
            for item in assignments
        ),
        "ranged_assignment_count": sum(
            item.get("assignment_semantics") == "model_valid_dc_operating_region"
            for item in assignments
        ),
        "recommended_route": (
            "direct_simulation"
            if assignments
            and all(
                item.get("assignment_semantics")
                == "model_valid_dc_operating_point"
                for item in assignments
            )
            else (
                "select_vout_within_feasible_window"
                if assignments
                else "blocked"
            )
        ),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "search_profile": aggregate_profile.to_dict(),
        "assignments": assignments,
        "next_stage": (
            "ngspice_dc_confirmation"
            if assignments
            and all(
                item.get("assignment_semantics")
                == "model_valid_dc_operating_point"
                for item in assignments
            )
            else (
                "select_output_voltage_within_feasible_window"
                if assignments
                else "diagnose_empty_intersection"
            )
        ),
    }


def _search_profile_markdown(profile: Mapping[str, Any]) -> str:
    lines = [
        "# OpenAMS Step 5 Search Profile",
        "",
        f"- Recursion nodes: {int(profile.get('recursion_nodes', 0))}",
        f"- Terminal states: {int(profile.get('terminal_states', 0))}",
        f"- Accepted solutions: {int(profile.get('accepted_solutions', 0))}",
        f"- Maximum depth: {int(profile.get('max_depth', 0))}",
        f"- Solution-limit hits: {int(profile.get('solution_limit_hits', 0))}",
        f"- Unique exact states: {int(profile.get('unique_exact_states', 0))}",
        f"- Repeated exact states observed: {int(profile.get('repeated_exact_states_observed', 0))}",
        "",
        "## Per-group activity",
        "",
        "| Group | Calls | Choices | Empty joins |",
        "|---|---:|---:|---:|",
    ]
    calls = profile.get("group_calls", {})
    choices = profile.get("group_choices", {})
    empty = profile.get("group_empty", {})
    groups = sorted(set(calls) | set(choices) | set(empty))
    for group in groups:
        lines.append(
            f"| {group} | {int(calls.get(group, 0))} | "
            f"{int(choices.get(group, 0))} | {int(empty.get(group, 0))} |"
        )
    rejections = profile.get("rejection_counts", {})
    lines.extend(["", "## Rejections", "", "| Reason | Count |", "|---|---:|"])
    for reason, count in sorted(rejections.items()):
        lines.append(f"| {reason} | {int(count)} |")
    return "\n".join(lines) + "\n"


def write_generic_complete_assignments(
    compiled_model_path: Path,
    independent_regions_path: Path,
    dependent_regions_path: Path,
    output_json: Path,
    output_csv: Path,
    **kwargs: Any,
) -> Mapping[str, Any]:
    artifact = build_generic_complete_assignments(
        compiled_model_path,
        independent_regions_path,
        dependent_regions_path,
        **kwargs,
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(artifact, indent=2, default=str) + "\n", encoding="utf-8")
    profile = artifact.get("search_profile", {})
    profile_json = output_json.with_name("search_profile.json")
    profile_markdown = output_json.with_name("SEARCH_PROFILE.md")
    profile_json.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    profile_markdown.write_text(_search_profile_markdown(profile), encoding="utf-8")
    assignments = artifact["assignments"]
    if assignments:
        scalar_rows = [
            {key: value for key, value in row.items() if isinstance(value, (str, int, float, bool))}
            for row in assignments
        ]
        fields = sorted({key for row in scalar_rows for key in row}, key=lambda key: (key != "assignment_id", key))
        with output_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(scalar_rows)
    else:
        output_csv.write_text("assignment_id\n", encoding="utf-8")
    return artifact

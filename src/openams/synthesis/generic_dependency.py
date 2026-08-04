"""Topology-independent Step-4 dependency propagation.

The engine intentionally separates three concerns:

1. propagate declared linear current equations over independent intervals;
2. recover legal total-width intervals from the technology table;
3. derive conservative voltage regions from topology, supplies, and device rows.

It does not manufacture full correlated operating points. Correlation and final
KCL/KVL/device-row joins remain Step 5 responsibilities and are reported as
explicitly deferred evidence.
"""
from __future__ import annotations

import ast
import math
import re
from typing import Any, Mapping, Sequence

from .dependent_regions import (
    DependentRegionError,
    TechRow,
    _clip_interval,
    _device_map,
    _derived_width_interval,
    _filtered_rows,
    _interval,
    _num,
    _values_interval,
    _width_policy,
)

_VAR_RE = re.compile(r"\b([iwv]_[A-Za-z0-9_]+(?:_a|_um|_v)?)\b", re.I)



def _canonical_variable(name: str) -> str:
    token = name.strip().lower()
    if re.fullmatch(r"i_m\d+", token):
        return token + "_a"
    if re.fullmatch(r"w_m\d+", token):
        return token + "_um"
    if re.fullmatch(r"v[a-z0-9_]+", token) and not token.endswith("_v"):
        return token + "_v"
    return token


def _canonical_expression(expression: str) -> str:
    return re.sub(
        r"\b(?:i_m\d+|w_m\d+|v[a-z][a-z0-9_]*)\b",
        lambda match: _canonical_variable(match.group(0)),
        expression,
        flags=re.I,
    )

def _domain_interval(domain: Mapping[str, Any]) -> dict[str, float]:
    lo = domain.get("technology_minimum", domain.get("minimum"))
    hi = domain.get("technology_maximum", domain.get("maximum"))
    if lo is None or hi is None:
        lo = domain.get("declared_effective_minimum")
        hi = domain.get("declared_effective_maximum")
    return _interval(_num(lo, "domain minimum"), _num(hi, "domain maximum"))


def _eval_interval(expression: str, values: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    tree = ast.parse(expression.strip(), mode="eval")

    def ev(node: ast.AST) -> tuple[float, float]:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            value = float(node.value)
            return value, value
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise KeyError(node.id)
            item = values[node.id]
            return _num(item["minimum"], "minimum"), _num(item["maximum"], "maximum")
        if isinstance(node, ast.UnaryOp):
            lo, hi = ev(node.operand)
            if isinstance(node.op, ast.USub):
                return -hi, -lo
            if isinstance(node.op, ast.UAdd):
                return lo, hi
        if isinstance(node, ast.BinOp):
            alo, ahi = ev(node.left)
            blo, bhi = ev(node.right)
            if isinstance(node.op, ast.Add):
                return alo + blo, ahi + bhi
            if isinstance(node.op, ast.Sub):
                return alo - bhi, ahi - blo
            if isinstance(node.op, ast.Mult):
                products = (alo * blo, alo * bhi, ahi * blo, ahi * bhi)
                return min(products), max(products)
            if isinstance(node.op, ast.Div):
                if blo <= 0.0 <= bhi:
                    raise DependentRegionError("interval division crosses zero")
                quotients = (alo / blo, alo / bhi, ahi / blo, ahi / bhi)
                return min(quotients), max(quotients)
        raise DependentRegionError(f"unsupported dependency expression node {type(node).__name__}")

    lo, hi = ev(tree)
    return _interval(lo, hi)


def _equations(intent: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    circuit = intent.get("circuit_intent", {})
    for section in ("current_relations", "size_relations"):
        for item in circuit.get(section, []) or []:
            equation = str(item.get("equation", ""))
            # Compound width equalities are expanded.
            for fragment in equation.split(" and "):
                if "=" not in fragment:
                    continue
                left, right = fragment.split("=", 1)
                result.append((
                    str(item.get("id", section)),
                    _canonical_variable(left),
                    _canonical_expression(right),
                ))
    return result


def propagate_linear_intervals(
    intent: Mapping[str, Any],
    seeds: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    values = {name: _domain_interval(value) for name, value in seeds.items()}
    pending = _equations(intent)
    evidence: list[dict[str, Any]] = []

    while pending:
        next_pending: list[tuple[str, str, str]] = []
        progress = False
        for relation_id, left, right in pending:
            try:
                interval = _eval_interval(right, values)
            except KeyError:
                next_pending.append((relation_id, left, right))
                continue
            values[left] = interval
            evidence.append({"relation_id": relation_id, "left": left, "right": right, "interval": interval})
            progress = True
        if not progress:
            break
        pending = next_pending

    unresolved = [
        {"relation_id": relation_id, "left": left, "right": right}
        for relation_id, left, right in pending
    ]
    return values, evidence + ([{"unresolved_equations": unresolved}] if unresolved else [])


def _device_current_name(device: str) -> str:
    return f"i_{device.lower()}_a"


def _device_width_name(device: str) -> str:
    return f"w_{device.lower()}_um"


def recover_width_regions(
    model: Mapping[str, Any],
    rows: Sequence[TechRow],
    intervals: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    devices = _device_map(model)
    rules = model["project_inputs"]["design_rules"]
    device_rules = rules["device_constraints"]["all_mos"]
    length_um = _num(device_rules["length_um"], "length_um")
    body_limit = _num(device_rules["body_voltage_abs_max_v"], "body limit")
    policy = _width_policy(model)
    regions: dict[str, dict[str, Any]] = {}
    support: dict[str, Any] = {}

    for device_name, device in devices.items():
        if str(device.get("kind", "")).lower() != "mos":
            continue
        current_name = _device_current_name(device_name)
        width_name = _device_width_name(device_name)
        if current_name not in intervals:
            continue
        feasible = _filtered_rows(rows, device, length_um=length_um, body_limit_v=body_limit)
        region = _derived_width_interval(feasible, intervals[current_name], policy)
        region["derivation"] = "technology_current_density_scaling"
        region["device"] = device_name
        regions[width_name] = region
        support[device_name] = {"filtered_row_count": len(feasible)}

    return regions, support


def _supply_bounds(model: Mapping[str, Any]) -> tuple[float, float, Mapping[str, Any]]:
    rules = model["project_inputs"]["design_rules"]
    operating = rules.get("operating_conditions", {})
    return _num(operating.get("vss_v", 0.0), "vss"), _num(operating["vdd_v"], "vdd"), operating


def recover_voltage_regions(
    model: Mapping[str, Any],
    rows: Sequence[TechRow],
    declared: set[str],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    vss, vdd, operating = _supply_bounds(model)
    devices = _device_map(model)
    rules = model["project_inputs"]["design_rules"]
    device_rules = rules["device_constraints"]["all_mos"]
    length_um = _num(device_rules["length_um"], "length_um")
    body_limit = _num(device_rules["body_voltage_abs_max_v"], "body limit")
    regions: dict[str, dict[str, Any]] = {}
    deferred: list[str] = []

    # Absolute bias voltages: derive candidate supply-bounded ranges from VGS.
    bias_semantics = model["project_inputs"]["design_intent"].get("circuit_intent", {}).get("bias_semantics", {})
    for variable, definition in bias_semantics.items():
        if variable not in declared or variable in regions:
            continue
        drives = list(definition.get("drives", []))
        device_name = str(drives[0]).upper() if drives else ""
        device = devices.get(device_name)
        if device is None:
            continue
        feasible = _filtered_rows(rows, device, length_um=length_um, body_limit_v=body_limit)
        polarity = "pmos" if "pfet" in str(device.get("model", "")).lower() else "nmos"
        terminals = device.get("terminals", {})
        source = str(terminals.get("source", "")).lower()
        source_value = None
        if source in {"vss", "0", "gnd"}:
            source_value = vss
        elif source == "vdd":
            source_value = vdd
        if source_value is not None:
            values = [source_value + row.vgs_v if polarity == "nmos" else source_value - row.vgs_v for row in feasible]
            region = _clip_interval(_values_interval(values, variable), vss, vdd)
            region.update({"derivation": "technology_vgs_from_fixed_source", "device": device_name})
            regions[variable] = region
        else:
            regions[variable] = {**_interval(vss, vdd), "derivation": "supply_bounded_deferred_source_voltage", "device": device_name}
            deferred.append(f"{variable}: exact source voltage correlation")

    # Named node voltages use conservative supply bounds. Special-case input-tail
    # source when input common mode is available, using M1 VGS support.
    vin_cm = operating.get("vin_cm_v")
    for variable in sorted(declared):
        if not variable.endswith("_v") or variable in regions:
            continue
        if variable == "vtail_v" and vin_cm is not None and "M1" in devices:
            feasible = _filtered_rows(rows, devices["M1"], length_um=length_um, body_limit_v=body_limit)
            values = [_num(vin_cm, "vin_cm") - row.vgs_v for row in feasible]
            valid = [value for value in values if vss <= value <= vdd]
            if valid:
                regions[variable] = {**_values_interval(valid, variable), "derivation": "vin_cm_minus_vgs"}
                continue
        regions[variable] = {**_interval(vss, vdd), "derivation": "supply_bounded_conservative_region"}
        deferred.append(f"{variable}: exact topology/node correlation")

    return regions, deferred


def build_generic_group_results(
    model: Mapping[str, Any],
    independent: Mapping[str, Any],
    rows: Sequence[TechRow],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    intent = model["project_inputs"]["design_intent"]
    seeds = independent["domains"]
    intervals, equation_evidence = propagate_linear_intervals(intent, seeds)
    width_regions, technology_support = recover_width_regions(model, rows, intervals)

    declared = {item["id"] for item in model["synthesis_interface"]["dependent_quantities"]}
    voltage_regions, deferred = recover_voltage_regions(model, rows, declared)

    all_regions: dict[str, Any] = {}
    for name, value in intervals.items():
        if name in declared:
            all_regions[name] = {**value, "derivation": "linear_dependency_propagation"}
    for name, value in width_regions.items():
        if name in declared:
            all_regions[name] = value
    all_regions.update({name: value for name, value in voltage_regions.items() if name in declared})

    groups_out: list[dict[str, Any]] = []
    for group in intent["assignment_synthesis"]["groups"]:
        group_id = str(group["id"])
        devices = {str(item).upper() for item in group.get("devices", [])}
        group_regions = {
            name: value
            for name, value in all_regions.items()
            if any(f"_m{device[1:].lower()}_" in name.lower() for device in devices)
            or name in set(group.get("derives", []))
        }
        # Include non-device node/bias quantities by dependency-contract declaration.
        contract = intent.get("dependent_derivation_contract", {}).get("groups", {}).get(group_id, {})
        for name in contract.get("derives", []) or []:
            if name in all_regions:
                group_regions[name] = all_regions[name]
        groups_out.append({
            "group_id": group_id,
            "solver": "generic_dependency_graph",
            "status": "PASS",
            "depends_on": list(group.get("depends_on", [])),
            "dependent_regions": group_regions,
            "equation_evidence": equation_evidence,
            "technology_support": technology_support,
            "correlation_status": "DEFERRED_TO_STEP_5",
        })

    return groups_out, all_regions, deferred

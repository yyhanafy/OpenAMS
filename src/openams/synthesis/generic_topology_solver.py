"""Generic topology-driven MOS assignment solver with full physical correlation.

Topology-specific knowledge is supplied by a data contract. The solver itself
implements only reusable primitives:

- expressions and equality constraints
- row-backed current-density scaling
- matched-device row/value constraints
- node voltage propagation from MOS terminals
- coupled current/width equations
- interpolation of a required current density at fixed terminal voltage
- saturation and physical width checks
- most-constrained-device-first backtracking
"""

from __future__ import annotations

import ast
import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class GenericSolverError(ValueError):
    pass


@dataclass(frozen=True)
class TechnologyRow:
    index: int
    polarity: str
    model: str
    length_um: float
    width_um: float
    vgs_v: float
    vds_v: float
    vbs_v: float
    id_a: float
    vdsat_v: float
    saturated: bool

    @property
    def density_a_per_um(self) -> float:
        return self.id_a / self.width_um


@dataclass
class PartialAssignment:
    values: dict[str, float]
    device_rows: dict[str, TechnologyRow]
    interpolated_devices: dict[str, dict[str, Any]]
    provenance: dict[str, Any]

    def clone(self) -> "PartialAssignment":
        return PartialAssignment(
            values=dict(self.values),
            device_rows=dict(self.device_rows),
            interpolated_devices={
                name: dict(value)
                for name, value in self.interpolated_devices.items()
            },
            provenance=dict(self.provenance),
        )


def _num(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GenericSolverError(f"{name} must be numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise GenericSolverError(f"{name} must be finite: {value!r}")
    return result


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in ("", None):
            return row[name]
    raise GenericSolverError(f"missing fields {names!r}")


def load_technology(path: Path) -> tuple[TechnologyRow, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = tuple(
            TechnologyRow(
                index=index,
                polarity=str(raw["polarity"]).lower(),
                model=str(raw["model"]),
                length_um=_num(raw["length_um"], "length_um"),
                width_um=_num(raw["width_um"], "width_um"),
                vgs_v=_num(_first(raw, "vgs_v", "vgs_abs_v"), "vgs"),
                vds_v=_num(_first(raw, "vds_v", "vds_abs_v"), "vds"),
                vbs_v=_num(_first(raw, "vbs_v", "vbs_abs_v"), "vbs"),
                id_a=_num(_first(raw, "id_abs_a", "id_a", "id"), "id"),
                vdsat_v=_num(
                    _first(raw, "vdsat_v", "vdsat_abs_v"),
                    "vdsat",
                ),
                saturated=_truth(raw.get("saturated", True)),
            )
            for index, raw in enumerate(reader)
        )
    if not rows:
        raise GenericSolverError(f"empty technology table: {path}")
    return rows


class SafeExpression:
    ALLOWED = {
        ast.Expression, ast.BinOp, ast.UnaryOp,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
        ast.USub, ast.UAdd, ast.Load, ast.Name, ast.Constant,
    }

    def __init__(self, expression: str):
        self.expression = expression
        self.tree = ast.parse(expression, mode="eval")
        for node in ast.walk(self.tree):
            if type(node) not in self.ALLOWED:
                raise GenericSolverError(
                    f"unsupported expression element {type(node).__name__}"
                )

    @property
    def names(self) -> set[str]:
        return {
            node.id
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Name)
        }

    def evaluate(self, values: Mapping[str, float]) -> float:
        missing = self.names - set(values)
        if missing:
            raise KeyError(sorted(missing))
        return float(
            eval(
                compile(self.tree, "<constraint>", "eval"),
                {"__builtins__": {}},
                dict(values),
            )
        )


def _close(a: float, b: float, *, atol: float, rtol: float) -> bool:
    return abs(a - b) <= max(
        atol,
        rtol * max(abs(a), abs(b), 1e-30),
    )


def _minimum_nf(width_um: float, policy: Mapping[str, Any]) -> int | None:
    if not (
        float(policy["total_width_min_um"])
        <= width_um
        <= float(policy["total_width_max_um"])
    ):
        return None
    for nf in range(int(policy["nf_min"]), int(policy["nf_max"]) + 1):
        finger = width_um / nf
        if (
            float(policy["finger_width_min_um"])
            <= finger
            <= float(policy["finger_width_max_um"])
        ):
            return nf
    return None


def _device_map(model: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for device in model["topology"]["devices"]:
        if str(device.get("kind", "")).lower() != "mos":
            continue
        raw = str(device["name"])
        name = raw[1:] if raw.upper().startswith("X") else raw
        result[name.upper()] = device
    return result


def _polarity(model_name: str) -> str:
    token = model_name.lower()
    if "pfet" in token or "pmos" in token:
        return "pmos"
    if "nfet" in token or "nmos" in token:
        return "nmos"
    raise GenericSolverError(f"cannot infer polarity from {model_name!r}")


def _filter_rows(
    rows: Sequence[TechnologyRow],
    *,
    model_name: str,
    length_um: float,
    body_limit_v: float,
) -> tuple[TechnologyRow, ...]:
    return tuple(
        row
        for row in rows
        if row.model == model_name
        and math.isclose(row.length_um, length_um, abs_tol=1e-12)
        and abs(row.vbs_v) <= body_limit_v + 1e-15
        and row.saturated
        and row.id_a > 0.0
        and row.width_um > 0.0
    )


def _node_from_terminal(
    *,
    polarity: str,
    terminal: str,
    source_voltage: float,
    vgs_v: float,
    vds_v: float,
) -> float:
    if terminal == "gate":
        return source_voltage + vgs_v if polarity == "nmos" else source_voltage - vgs_v
    if terminal == "drain":
        return source_voltage + vds_v if polarity == "nmos" else source_voltage - vds_v
    raise GenericSolverError(f"unsupported terminal {terminal!r}")


def _interpolate_density(
    rows: Sequence[TechnologyRow],
    target_density: float,
) -> dict[str, Any] | None:
    ordered = sorted(rows, key=lambda row: row.density_a_per_um)

    for row in ordered:
        if math.isclose(
            row.density_a_per_um,
            target_density,
            rel_tol=1e-12,
            abs_tol=1e-18,
        ):
            return {
                "density_a_per_um": target_density,
                "vgs_v": row.vgs_v,
                "vds_v": row.vds_v,
                "vdsat_v": row.vdsat_v,
                "lower_row_index": row.index,
                "upper_row_index": row.index,
                "fraction": 0.0,
            }

    for lower, upper in zip(ordered, ordered[1:]):
        d0 = lower.density_a_per_um
        d1 = upper.density_a_per_um
        if d0 <= target_density <= d1 and d1 > d0:
            alpha = (target_density - d0) / (d1 - d0)
            return {
                "density_a_per_um": target_density,
                "vgs_v": lower.vgs_v + alpha * (upper.vgs_v - lower.vgs_v),
                "vds_v": lower.vds_v + alpha * (upper.vds_v - lower.vds_v),
                "vdsat_v": lower.vdsat_v + alpha * (upper.vdsat_v - lower.vdsat_v),
                "lower_row_index": lower.index,
                "upper_row_index": upper.index,
                "fraction": alpha,
            }

    return None


@dataclass
class SolverContext:
    model: Mapping[str, Any]
    contract: Mapping[str, Any]
    devices: dict[str, Mapping[str, Any]]
    rows_by_device: dict[str, tuple[TechnologyRow, ...]]
    width_policy: Mapping[str, Any]
    constraints: tuple["Constraint", ...]
    rejection_by_constraint: Counter
    rejection_by_device_trial: Counter


class Constraint:
    def __init__(self, raw: Mapping[str, Any]):
        self.raw = dict(raw)
        self.id = str(raw["id"])
        self.kind = str(raw["kind"])

    def propagate(
        self,
        assignment: PartialAssignment,
        context: SolverContext,
    ) -> bool:
        method = getattr(self, f"_propagate_{self.kind}", None)
        if method is None:
            raise GenericSolverError(f"unknown constraint kind {self.kind!r}")
        return bool(method(assignment, context))

    def _set_or_check(
        self,
        assignment: PartialAssignment,
        name: str,
        value: float,
        *,
        atol: float = 0.0,
        rtol: float = 0.0,
    ) -> bool:
        if name in assignment.values:
            return _close(
                assignment.values[name],
                value,
                atol=atol,
                rtol=rtol,
            )
        assignment.values[name] = value
        return True

    def _propagate_expression(self, a, c) -> bool:
        target = str(self.raw["target"])
        expr = SafeExpression(str(self.raw["expression"]))
        try:
            value = expr.evaluate(a.values)
        except KeyError:
            return True
        return self._set_or_check(
            a,
            target,
            value,
            atol=float(self.raw.get("absolute_tolerance", 0.0)),
            rtol=float(self.raw.get("relative_tolerance", 0.0)),
        )

    def _propagate_equal(self, a, c) -> bool:
        left = str(self.raw["left"])
        right = str(self.raw["right"])
        atol = float(self.raw.get("absolute_tolerance", 0.0))
        rtol = float(self.raw.get("relative_tolerance", 0.0))
        if left in a.values and right in a.values:
            return _close(a.values[left], a.values[right], atol=atol, rtol=rtol)
        if left in a.values:
            a.values[right] = a.values[left]
        elif right in a.values:
            a.values[left] = a.values[right]
        return True

    def _propagate_bounds(self, a, c) -> bool:
        variable = str(self.raw["variable"])
        if variable not in a.values:
            return True
        return (
            float(self.raw["minimum"])
            <= a.values[variable]
            <= float(self.raw["maximum"])
        )


    def _propagate_copy_width_realization(self, a, c) -> bool:
        """Copy total width, NF, and finger width between matched devices."""
        source = str(self.raw["source_device"]).upper()
        target = str(self.raw["target_device"]).upper()

        source_width = str(self.raw.get(
            "source_width",
            f"w_{source.lower()}_um",
        ))
        target_width = str(self.raw.get(
            "target_width",
            f"w_{target.lower()}_um",
        ))

        source_nf = f"nf_{source.lower()}"
        target_nf = f"nf_{target.lower()}"
        source_finger = f"w_finger_{source.lower()}_um"
        target_finger = f"w_finger_{target.lower()}_um"

        required = (source_width, source_nf, source_finger)
        if any(name not in a.values for name in required):
            return True

        pairs = (
            (target_width, a.values[source_width]),
            (target_nf, a.values[source_nf]),
            (target_finger, a.values[source_finger]),
        )
        for name, value in pairs:
            if not self._set_or_check(
                a,
                name,
                value,
                atol=1e-12,
                rtol=1e-12,
            ):
                return False
        return True

    def _propagate_width_from_row(self, a, c) -> bool:
        device = str(self.raw["device"]).upper()
        current = str(self.raw["current"])
        width_name = str(self.raw["width"])
        if device not in a.device_rows or current not in a.values:
            return True

        width = (
            a.values[current]
            / a.device_rows[device].density_a_per_um
        )
        nf = _minimum_nf(width, c.width_policy)
        if nf is None:
            return False

        if not self._set_or_check(
            a, width_name, width, atol=1e-9, rtol=1e-10
        ):
            return False

        a.values[f"nf_{device.lower()}"] = float(nf)
        a.values[f"w_finger_{device.lower()}_um"] = width / nf
        return True


    def _propagate_matched_operating_point(self, a, c) -> bool:
        """Match selected device quantities without forcing identical VDS rows.

        Useful for symmetric devices that share VGS/current density but may have
        different drain voltages because their drains connect to different nodes.
        """
        left = str(self.raw["left_device"]).upper()
        right = str(self.raw["right_device"]).upper()
        if left not in a.device_rows or right not in a.device_rows:
            return True

        lrow = a.device_rows[left]
        rrow = a.device_rows[right]
        atol = float(self.raw.get("absolute_tolerance", 0.0))
        rtol = float(self.raw.get("relative_tolerance", 0.0))

        quantities = self.raw.get(
            "quantities",
            ["vgs_v", "vbs_v", "density_a_per_um"],
        )
        for quantity in quantities:
            lv = getattr(lrow, quantity)
            rv = getattr(rrow, quantity)
            if not _close(lv, rv, atol=atol, rtol=rtol):
                return False
        return True

    def _propagate_matched_row(self, a, c) -> bool:
        left = str(self.raw["left_device"]).upper()
        right = str(self.raw["right_device"]).upper()
        if left not in a.device_rows or right not in a.device_rows:
            return True

        lrow = a.device_rows[left]
        rrow = a.device_rows[right]
        fields = self.raw.get(
            "fields",
            ["vgs_v", "vds_v", "vbs_v", "density_a_per_um"],
        )
        atol = float(self.raw.get("absolute_tolerance", 0.0))
        rtol = float(self.raw.get("relative_tolerance", 0.0))

        for field in fields:
            lv = getattr(lrow, field)
            rv = getattr(rrow, field)
            if not _close(lv, rv, atol=atol, rtol=rtol):
                return False
        return True

    def _device_voltage_values(
        self,
        assignment: PartialAssignment,
        device: str,
    ) -> tuple[float, float] | None:
        if device in assignment.interpolated_devices:
            item = assignment.interpolated_devices[device]
            return float(item["vgs_v"]), float(item["vds_v"])
        if device in assignment.device_rows:
            row = assignment.device_rows[device]
            return row.vgs_v, row.vds_v
        return None

    def _propagate_terminal_node(self, a, c) -> bool:
        device = str(self.raw["device"]).upper()
        source_node = str(self.raw["source_node"])
        target_node = str(self.raw["target_node"])
        terminal = str(self.raw["terminal"])

        if source_node not in a.values:
            return True

        voltages = self._device_voltage_values(a, device)
        if voltages is None:
            return True

        vgs_v, vds_v = voltages
        model_name = str(c.devices[device]["model"])
        value = _node_from_terminal(
            polarity=_polarity(model_name),
            terminal=terminal,
            source_voltage=a.values[source_node],
            vgs_v=vgs_v,
            vds_v=vds_v,
        )

        return self._set_or_check(
            a,
            target_node,
            value,
            atol=float(self.raw.get("absolute_tolerance", 0.025)),
            rtol=0.0,
        )

    def _propagate_diode_connected(self, a, c) -> bool:
        device = str(self.raw["device"]).upper()
        if device not in a.device_rows:
            return True
        row = a.device_rows[device]
        return abs(row.vgs_v - row.vds_v) <= float(
            self.raw.get("absolute_tolerance", 0.025)
        )

    def _propagate_saturation_margin(self, a, c) -> bool:
        device = str(self.raw["device"]).upper()
        minimum = float(self.raw.get("minimum_margin_v", 0.0))

        if device in a.interpolated_devices:
            item = a.interpolated_devices[device]
            return float(item["vds_v"]) - float(item["vdsat_v"]) >= minimum

        if device not in a.device_rows:
            return True
        row = a.device_rows[device]
        return row.vds_v - row.vdsat_v >= minimum


    def _propagate_copy_device_row(self, a, c) -> bool:
        source = str(self.raw["source_device"]).upper()
        target = str(self.raw["target_device"]).upper()
        if source not in a.device_rows:
            return True

        source_row = a.device_rows[source]
        if target in a.device_rows:
            return a.device_rows[target].index == source_row.index

        a.device_rows[target] = source_row
        a.provenance[
            f"{target.lower()}_technology_row_index"
        ] = source_row.index
        return True

    def _propagate_row_density(self, a, c) -> bool:
        device = str(self.raw["device"]).upper()
        target = str(self.raw["target"])
        if device not in a.device_rows:
            return True
        return self._set_or_check(
            a,
            target,
            a.device_rows[device].density_a_per_um,
            atol=1e-18,
            rtol=1e-12,
        )

    def _propagate_coupled_density(self, a, c) -> bool:
        """Derive target device current density from a generic expression."""
        target_device = str(self.raw["target_device"]).upper()
        expression = SafeExpression(str(self.raw["density_expression"]))

        try:
            target_density = expression.evaluate(a.values)
        except KeyError:
            return True

        fixed_vds_variable = str(self.raw["fixed_vds_variable"])
        if fixed_vds_variable not in a.values:
            return True

        fixed_vds = a.values[fixed_vds_variable]
        tolerance = float(self.raw.get("vds_tolerance", 1e-9))
        source_rows = [
            row
            for row in c.rows_by_device[target_device]
            if abs(row.vds_v - fixed_vds) <= tolerance
        ]
        if not source_rows:
            return False

        interpolation = _interpolate_density(source_rows, target_density)
        if interpolation is None:
            return False

        existing = a.interpolated_devices.get(target_device)
        if existing is not None:
            return _close(
                float(existing["density_a_per_um"]),
                target_density,
                atol=1e-18,
                rtol=1e-10,
            )

        a.interpolated_devices[target_device] = interpolation
        a.provenance[
            f"{target_device.lower()}_lower_technology_row_index"
        ] = interpolation["lower_row_index"]
        a.provenance[
            f"{target_device.lower()}_upper_technology_row_index"
        ] = interpolation["upper_row_index"]
        a.provenance[
            f"{target_device.lower()}_interpolation_fraction"
        ] = interpolation["fraction"]
        return True

    def _propagate_common_current_interval(self, a, c) -> bool:
        left_device = str(self.raw["left_device"]).upper()
        right_device = str(self.raw["right_device"]).upper()
        output_current = str(self.raw["output_current"])

        if left_device not in a.interpolated_devices:
            return True
        if right_device not in a.device_rows:
            return True

        left_density = float(
            a.interpolated_devices[left_device]["density_a_per_um"]
        )
        right_density = a.device_rows[right_device].density_a_per_um

        width_min = float(c.width_policy["total_width_min_um"])
        width_max = float(c.width_policy["total_width_max_um"])

        current_min = max(
            left_density * width_min,
            right_density * width_min,
        )
        current_max = min(
            left_density * width_max,
            right_density * width_max,
        )
        if current_min > current_max:
            return False

        policy = str(self.raw.get("selection", "minimum"))
        selected = current_min if policy == "minimum" else current_max
        if not self._set_or_check(
            a,
            output_current,
            selected,
            atol=1e-18,
            rtol=1e-10,
        ):
            return False

        a.values[f"{output_current}_minimum"] = current_min
        a.values[f"{output_current}_maximum"] = current_max
        return True

    def _propagate_width_from_density(self, a, c) -> bool:
        device = str(self.raw["device"]).upper()
        current = str(self.raw["current"])
        width = str(self.raw["width"])

        if current not in a.values:
            return True

        if device in a.interpolated_devices:
            density = float(
                a.interpolated_devices[device]["density_a_per_um"]
            )
        elif device in a.device_rows:
            density = a.device_rows[device].density_a_per_um
        else:
            return True

        total_width = a.values[current] / density
        nf = _minimum_nf(total_width, c.width_policy)
        if nf is None:
            return False

        if not self._set_or_check(
            a,
            width,
            total_width,
            atol=1e-9,
            rtol=1e-10,
        ):
            return False

        a.values[f"nf_{device.lower()}"] = float(nf)
        a.values[f"w_finger_{device.lower()}_um"] = total_width / nf
        return True


def _propagate_all(
    assignment: PartialAssignment,
    context: SolverContext,
) -> bool:
    for _ in range(100):
        before = (
            len(assignment.values),
            len(assignment.interpolated_devices),
        )
        for constraint in context.constraints:
            if not constraint.propagate(assignment, context):
                context.rejection_by_constraint[constraint.id] += 1
                assignment.provenance["_last_failed_constraint"] = constraint.id
                return False
        after = (
            len(assignment.values),
            len(assignment.interpolated_devices),
        )
        if after == before:
            return True
    raise GenericSolverError("constraint propagation did not converge")


def _candidate_rows_for_device(
    device: str,
    assignment: PartialAssignment,
    context: SolverContext,
) -> list[TechnologyRow]:
    # Interpolated devices are not row-selected.
    if device in assignment.interpolated_devices:
        return []

    result = []
    for row in context.rows_by_device[device]:
        trial = assignment.clone()
        trial.device_rows[device] = row
        trial.provenance[
            f"{device.lower()}_technology_row_index"
        ] = row.index
        if _propagate_all(trial, context):
            result.append(row)
        else:
            failed = trial.provenance.get(
                "_last_failed_constraint",
                "unknown",
            )
            context.rejection_by_device_trial[
                f"{device}:{failed}"
            ] += 1
    return result


def _next_device(
    assignment: PartialAssignment,
    context: SolverContext,
) -> tuple[str, list[TechnologyRow]] | None:
    """Choose the next row-selected device in dependency order.

    The contract compiler owns the order. Interpolation-only and copied devices
    are produced by generic constraints and are never enumerated.
    """
    row_selected = context.contract.get(
        "row_selected_devices",
        context.contract["devices"],
    )

    for raw in row_selected:
        device = str(raw).upper()
        if device in assignment.device_rows:
            continue
        if device in assignment.interpolated_devices:
            continue
        return device, _candidate_rows_for_device(
            device,
            assignment,
            context,
        )

    return None


def solve_generic_assignments(
    compiled_model_path: Path,
    independent_regions_path: Path,
    contract_path: Path,
    *,
    max_solutions: int | None = None,
    max_partials: int | None = None,
    progress_every: int = 1000,
) -> Mapping[str, Any]:
    model = json.loads(compiled_model_path.read_text(encoding="utf-8"))
    independent = json.loads(
        independent_regions_path.read_text(encoding="utf-8")
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    technology_path = Path(model["technology"]["source_path"]).resolve()
    technology_rows = load_technology(technology_path)

    devices = _device_map(model)
    rules = model["project_inputs"]["design_rules"]
    all_mos = rules["device_constraints"]["all_mos"]

    requested_devices = {
        str(name).upper()
        for name in contract.get(
            "row_selected_devices",
            contract["devices"],
        )
    }
    requested_devices.update(
        str(name).upper()
        for name in contract.get("interpolated_devices", [])
    )
    requested_devices.update(
        str(name).upper()
        for name in contract.get("copied_devices", [])
    )
    rows_by_device = {
        name: _filter_rows(
            technology_rows,
            model_name=str(device["model"]),
            length_um=float(all_mos["length_um"]),
            body_limit_v=float(all_mos["body_voltage_abs_max_v"]),
        )
        for name, device in devices.items()
        if name in requested_devices
    }

    context = SolverContext(
        model=model,
        contract=contract,
        devices=devices,
        rows_by_device=rows_by_device,
        width_policy=contract["width_policy"],
        constraints=tuple(
            Constraint(raw)
            for raw in contract["constraints"]
        ),
        rejection_by_constraint=Counter(),
        rejection_by_device_trial=Counter(),
    )

    seeds = [
        PartialAssignment(
            values={
                name: float(value)
                for name, value in contract.get("constants", {}).items()
            },
            device_rows={},
            interpolated_devices={},
            provenance={},
        )
    ]

    # Enumerate only point-set independent domains. Continuous variables are
    # bounded by contract rules and become fixed through device constraints.
    for variable in contract["independent_variables"]:
        domain = independent["domains"][variable]
        values = domain.get("candidate_values") or []
        if not values:
            continue
        seeds = [
            PartialAssignment(
                values={**seed.values, variable: float(value)},
                device_rows=dict(seed.device_rows),
                interpolated_devices=dict(seed.interpolated_devices),
                provenance=dict(seed.provenance),
            )
            for seed in seeds
            for value in values
        ]

    solutions: list[dict[str, Any]] = []
    statistics = {
        "seed_count": len(seeds),
        "partials": 0,
        "early_rejections": 0,
        "complete": 0,
        "partials_by_assigned_device_count": Counter(),
        "dead_end_by_next_device": Counter(),
        "missing_complete_quantity_sets": Counter(),
    }

    required_quantities = set(contract["required_complete_quantities"])

    stop_reason: str | None = None

    def search(assignment: PartialAssignment) -> None:
        nonlocal stop_reason

        if stop_reason is not None:
            return
        if max_solutions is not None and len(solutions) >= max_solutions:
            stop_reason = "max_solutions_reached"
            return
        if max_partials is not None and statistics["partials"] >= max_partials:
            stop_reason = "max_partials_reached"
            return

        statistics["partials"] += 1
        assigned_count = (
            len(assignment.device_rows)
            + len(assignment.interpolated_devices)
        )
        statistics["partials_by_assigned_device_count"][
            str(assigned_count)
        ] += 1

        if progress_every > 0 and statistics["partials"] % progress_every == 0:
            print(
                "[PROGRESS] "
                f"partials={statistics['partials']} "
                f"complete={statistics['complete']} "
                f"early_rejections={statistics['early_rejections']}",
                flush=True,
            )
        if not _propagate_all(assignment, context):
            statistics["early_rejections"] += 1
            return

        choice = _next_device(assignment, context)
        if choice is None:
            missing = sorted(required_quantities - set(assignment.values))
            if missing:
                statistics["early_rejections"] += 1
                statistics["missing_complete_quantity_sets"][
                    ",".join(missing)
                ] += 1
                return

            solutions.append(
                {
                    "assignment_id": (
                        f"generic_assignment_{len(solutions):06d}"
                    ),
                    **assignment.values,
                    **assignment.provenance,
                    "device_row_count": (
                        len(assignment.device_rows)
                        + len(assignment.interpolated_devices)
                    ),
                    "interpolated_device_count": len(
                        assignment.interpolated_devices
                    ),
                    "assignment_semantics": (
                        "complete_correlated_circuit_assignment"
                    ),
                    "route": "direct_simulation",
                }
            )
            statistics["complete"] += 1
            return

        device, rows = choice
        if not rows:
            statistics["early_rejections"] += 1
            statistics["dead_end_by_next_device"][device] += 1
            return

        for row in rows:
            child = assignment.clone()
            child.device_rows[device] = row
            child.provenance[
                f"{device.lower()}_technology_row_index"
            ] = row.index
            search(child)

    for seed in seeds:
        search(seed)

    statistics["partials_by_assigned_device_count"] = dict(
        statistics["partials_by_assigned_device_count"]
    )
    statistics["dead_end_by_next_device"] = dict(
        statistics["dead_end_by_next_device"]
    )
    statistics["missing_complete_quantity_sets"] = dict(
        statistics["missing_complete_quantity_sets"]
    )

    diagnostics = {
        "rejection_by_constraint": dict(
            context.rejection_by_constraint.most_common()
        ),
        "rejection_by_device_trial": dict(
            context.rejection_by_device_trial.most_common()
        ),
        "technology_rows_by_device": {
            name: len(device_rows)
            for name, device_rows in rows_by_device.items()
        },
    }

    return {
        "artifact": "openams.generic_topology_assignments",
        "schema_version": 2,
        "status": "PASS" if solutions else "FAIL",
        "circuit_name": model["circuit_name"],
        "solver": "generic_constraint_propagating_backtracking",
        "topology_specific_code": False,
        "contract_path": str(contract_path.resolve()),
        "technology_source": str(technology_path),
        "statistics": statistics,
        "diagnostics": diagnostics,
        "stop_reason": stop_reason,
        "assignment_count": len(solutions),
        "assignments": solutions,
        "next_stage": (
            "ngspice_dc_confirmation"
            if solutions
            else "diagnose_empty_search"
        ),
    }


def write_generic_assignments(
    compiled_model_path: Path,
    independent_regions_path: Path,
    contract_path: Path,
    output_path: Path,
    *,
    max_solutions: int | None = None,
    max_partials: int | None = None,
    progress_every: int = 1000,
) -> Mapping[str, Any]:
    artifact = solve_generic_assignments(
        compiled_model_path,
        independent_regions_path,
        contract_path,
        max_solutions=max_solutions,
        max_partials=max_partials,
        progress_every=progress_every,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return artifact

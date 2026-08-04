"""Generic independent-variable domain construction for OpenAMS.

Step 3 builds physically realizable domains for every variable declared
independent in the compiled circuit model.

Rules:
1. The design intent declares the electrical variable and its requested range.
2. Design rules, specifications, supplies, and technology support further bound it.
3. Device-backed current/terminal-voltage variables preserve technology-row evidence.
4. Node voltages are continuous supported intervals, not exact shared table samples.
5. ``total_width`` may exceed a single-finger limit and is realized by integer NF
   with Wfinger inside the technology-supported finger-width interval.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class IndependentDomainError(ValueError):
    """Raised when a declared independent domain cannot be constructed."""


@dataclass(frozen=True)
class TechnologyRow:
    index: int
    values: Mapping[str, Any]


_DEVICE_TOKEN = re.compile(r"(?:^|_)(m\d+)(?:_|$)", re.IGNORECASE)


def _number(value: Any, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise IndependentDomainError(
            f"{field!r} must be numeric, got {value!r}"
        ) from exc
    if not math.isfinite(result):
        raise IndependentDomainError(
            f"{field!r} must be finite, got {value!r}"
        )
    return result


def _optional_number(mapping: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        if name in mapping and mapping[name] not in ("", None):
            return _number(mapping[name], field=name)
    return None


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _unique(values: Iterable[float], *, digits: int = 15) -> list[float]:
    return sorted({round(float(value), digits) for value in values})


def load_technology_rows(path: Path) -> tuple[TechnologyRow, ...]:
    if not path.is_file():
        raise IndependentDomainError(f"technology CSV does not exist: {path}")

    rows: list[TechnologyRow] = []
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise IndependentDomainError(f"technology CSV has no header: {path}")
        for index, raw in enumerate(reader):
            rows.append(TechnologyRow(index=index, values=dict(raw)))

    if not rows:
        raise IndependentDomainError(f"technology CSV is empty: {path}")
    return tuple(rows)


def _device_from_variable(variable_id: str) -> str | None:
    match = _DEVICE_TOKEN.search(variable_id)
    return match.group(1).upper() if match else None


def _devices(model: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in model.get("topology", {}).get("devices", []):
        raw = str(item.get("name", ""))
        canonical = raw[1:] if raw.upper().startswith("X") else raw
        if canonical:
            result[canonical.upper()] = item
    return result


def _polarity(model_name: str) -> str:
    token = model_name.lower()
    if "pfet" in token or "pmos" in token:
        return "pmos"
    if "nfet" in token or "nmos" in token:
        return "nmos"
    raise IndependentDomainError(
        f"cannot infer polarity from model {model_name!r}"
    )


def _technology_path(
    compiled_model_path: Path,
    model: Mapping[str, Any],
) -> Path:
    direct = model.get("technology", {}).get("source_path")
    if isinstance(direct, str) and direct.strip():
        return Path(direct).expanduser().resolve()

    project = model.get("project_inputs", {})
    technology = project.get("technology", {})
    active = technology.get("active_source")
    entry = technology.get("sources", {}).get(active, {})
    source = entry.get("source") if isinstance(entry, Mapping) else None
    if not isinstance(source, str) or not source.strip():
        raise IndependentDomainError("compiled model has no technology source")

    input_dir: Path | None = None
    for value in model.get("source_inputs", {}).values():
        path = value.get("path") if isinstance(value, Mapping) else None
        if path:
            input_dir = Path(path).resolve().parent
            break
    return ((input_dir or compiled_model_path.parent) / source).resolve()


def _base_filters(
    model: Mapping[str, Any],
    device: Mapping[str, Any] | None,
) -> dict[str, Any]:
    rules = model.get("project_inputs", {}).get("design_rules", {})
    all_mos = rules.get("device_constraints", {}).get("all_mos", {})
    result: dict[str, Any] = {
        "required_region": all_mos.get("required_region"),
        "length_um": all_mos.get("length_um"),
        "body_voltage_abs_max_v": all_mos.get("body_voltage_abs_max_v"),
    }
    if device is not None:
        model_name = str(device.get("model", ""))
        result["device_model"] = model_name
        result["polarity"] = _polarity(model_name)
    return result


def _row_matches(row: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    model_name = filters.get("device_model")
    if model_name and str(row.get("model", "")) != str(model_name):
        return False

    polarity = filters.get("polarity")
    if polarity and str(row.get("polarity", "")).lower() != str(polarity).lower():
        return False

    length = filters.get("length_um")
    row_length = _optional_number(row, "length_um")
    if length is not None and row_length is not None:
        if not math.isclose(
            row_length, float(length), rel_tol=0.0, abs_tol=1e-12
        ):
            return False

    required_region = str(filters.get("required_region") or "").lower()
    if required_region == "saturation":
        if "saturated" in row and not _truth(row.get("saturated")):
            return False
        if "region" in row and str(row.get("region", "")).lower() != "saturation":
            return False

    body_limit = filters.get("body_voltage_abs_max_v")
    vbs = _optional_number(row, "vbs_v", "vbs_abs_v")
    if body_limit is not None and vbs is not None:
        if abs(vbs) > float(body_limit) + 1e-15:
            return False

    return True


def _declared_bounds(definition: Mapping[str, Any]) -> tuple[float, float]:
    minimum = _number(definition.get("minimum"), field="minimum")
    maximum = _number(definition.get("maximum"), field="maximum")
    if minimum > maximum:
        raise IndependentDomainError(
            f"minimum {minimum} exceeds maximum {maximum}"
        )
    return minimum, maximum


def _spec_bounds(
    model: Mapping[str, Any],
    variable_id: str,
) -> tuple[float | None, float | None]:
    if variable_id.lower() != "vout_v":
        return None, None
    output = (
        model.get("project_inputs", {})
        .get("specifications", {})
        .get("dc_validity", {})
        .get("output_voltage", {})
    )
    if not isinstance(output, Mapping):
        return None, None
    return (
        _number(output["min"], field="output_voltage.min")
        if output.get("min") is not None else None,
        _number(output["max"], field="output_voltage.max")
        if output.get("max") is not None else None,
    )


def _effective_bounds(
    model: Mapping[str, Any],
    variable_id: str,
    definition: Mapping[str, Any],
) -> tuple[float, float, dict[str, Any]]:
    minimum, maximum = _declared_bounds(definition)
    sources: dict[str, Any] = {
        "design_intent": {"minimum": minimum, "maximum": maximum}
    }

    rules = model.get("project_inputs", {}).get("design_rules", {})
    all_mos = rules.get("device_constraints", {}).get("all_mos", {})
    kind = str(definition.get("kind", "")).lower()

    # A single-device width is clipped by technology device limits.
    # A total electrical width is not clipped by the one-finger maximum;
    # it is checked for integer-finger realizability later.
    if kind == "width":
        rule_min = all_mos.get("width_min_um")
        rule_max = all_mos.get("width_max_um")
        if rule_min is not None:
            minimum = max(minimum, _number(rule_min, field="width_min_um"))
        if rule_max is not None:
            maximum = min(maximum, _number(rule_max, field="width_max_um"))
        sources["single_device_width_rules"] = {
            "minimum": rule_min,
            "maximum": rule_max,
        }

    spec_min, spec_max = _spec_bounds(model, variable_id)
    if spec_min is not None:
        minimum = max(minimum, spec_min)
    if spec_max is not None:
        maximum = min(maximum, spec_max)
    if spec_min is not None or spec_max is not None:
        sources["specifications"] = {
            "minimum": spec_min,
            "maximum": spec_max,
        }

    if kind == "node_voltage":
        operating = rules.get("operating_conditions", {})
        vss = _optional_number(operating, "vss_v", "vss")
        vdd = _optional_number(operating, "vdd_v", "vdd")
        if vss is not None:
            minimum = max(minimum, vss)
        if vdd is not None:
            maximum = min(maximum, vdd)
        sources["supply"] = {"minimum": vss, "maximum": vdd}

    if minimum > maximum:
        raise IndependentDomainError(
            f"empty bound intersection for {variable_id!r}"
        )

    sources["effective_before_technology"] = {
        "minimum": minimum,
        "maximum": maximum,
    }
    return minimum, maximum, sources


def _quantity_fields(kind: str, variable_id: str) -> tuple[str, ...]:
    token = kind.lower()
    variable = variable_id.lower()
    if token == "current" or variable.startswith("i_"):
        return ("id_abs_a", "id_a", "id")
    if token == "width" or variable.startswith("w_"):
        return ("width_um",)
    if token in {"vgs", "gate_source_voltage"} or "vgs" in variable:
        return ("vgs_v", "vgs_abs_v")
    if token in {"vds", "drain_source_voltage"} or "vds" in variable:
        return ("vds_v", "vds_abs_v")
    if token in {"vbs", "body_source_voltage"} or "vbs" in variable:
        return ("vbs_v", "vbs_abs_v")
    raise IndependentDomainError(
        f"unsupported technology-backed kind {kind!r} for {variable_id!r}"
    )


def _row_value(row: Mapping[str, Any], fields: Sequence[str]) -> float:
    value = _optional_number(row, *fields)
    if value is None:
        raise IndependentDomainError(
            f"technology row has none of {tuple(fields)!r}"
        )
    return value


def _technology_point_domain(
    variable_id: str,
    definition: Mapping[str, Any],
    rows: Sequence[TechnologyRow],
    filters: Mapping[str, Any],
    minimum: float,
    maximum: float,
) -> dict[str, Any]:
    fields = _quantity_fields(str(definition.get("kind", "")), variable_id)
    records: list[dict[str, Any]] = []

    for item in rows:
        if not _row_matches(item.values, filters):
            continue
        value = _row_value(item.values, fields)
        if not minimum <= value <= maximum:
            continue
        records.append(
            {
                "value": value,
                "technology_row_index": item.index,
                "model": item.values.get("model"),
                "polarity": item.values.get("polarity"),
                "length_um": _optional_number(item.values, "length_um"),
                "width_um": _optional_number(item.values, "width_um"),
                "vgs_v": _optional_number(
                    item.values, "vgs_v", "vgs_abs_v"
                ),
                "vds_v": _optional_number(
                    item.values, "vds_v", "vds_abs_v"
                ),
                "vbs_v": _optional_number(
                    item.values, "vbs_v", "vbs_abs_v"
                ),
                "id_abs_a": _optional_number(
                    item.values, "id_abs_a", "id_a", "id"
                ),
            }
        )

    values = _unique(record["value"] for record in records)
    if not values:
        raise IndependentDomainError(
            f"technology filtering produced no values for {variable_id!r}"
        )

    return {
        "domain_type": "technology_supported_point_set",
        "candidate_values": values,
        "candidate_count": len(values),
        "supporting_row_count": len(records),
        "technology_records": records,
        "technology_quantity_fields": list(fields),
        "technology_minimum": min(values),
        "technology_maximum": max(values),
    }


def _finger_width_interval(
    rows: Sequence[TechnologyRow],
    filters: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> tuple[float, float]:
    widths = _unique(
        width
        for item in rows
        if _row_matches(item.values, filters)
        for width in [_optional_number(item.values, "width_um")]
        if width is not None
    )
    if not widths:
        raise IndependentDomainError(
            "technology contains no legal finger widths for device context"
        )

    all_mos = rules.get("device_constraints", {}).get("all_mos", {})
    rule_min = all_mos.get("width_min_um")
    rule_max = all_mos.get("width_max_um")
    minimum = max(
        min(widths),
        _number(rule_min, field="width_min_um")
        if rule_min is not None else min(widths),
    )
    maximum = min(
        max(widths),
        _number(rule_max, field="width_max_um")
        if rule_max is not None else max(widths),
    )
    if minimum > maximum:
        raise IndependentDomainError("empty legal finger-width interval")
    return minimum, maximum


def _total_width_domain(
    variable_id: str,
    definition: Mapping[str, Any],
    rows: Sequence[TechnologyRow],
    filters: Mapping[str, Any],
    rules: Mapping[str, Any],
    minimum: float,
    maximum: float,
) -> dict[str, Any]:
    finger_cfg = definition.get("finger_realization", {})
    if not isinstance(finger_cfg, Mapping):
        finger_cfg = {}

    tech_min, tech_max = _finger_width_interval(rows, filters, rules)
    finger_min = max(
        tech_min,
        _number(finger_cfg["finger_width_min_um"], field="finger_width_min_um")
        if finger_cfg.get("finger_width_min_um") is not None else tech_min,
    )
    finger_max = min(
        tech_max,
        _number(finger_cfg["finger_width_max_um"], field="finger_width_max_um")
        if finger_cfg.get("finger_width_max_um") is not None else tech_max,
    )
    if finger_min > finger_max:
        raise IndependentDomainError(
            f"no legal finger width for {variable_id!r}"
        )

    nf_min_declared = int(finger_cfg.get("nf_min", 1))
    nf_max_declared = finger_cfg.get("nf_max")
    required_nf_max = max(1, math.ceil(maximum / finger_min))
    nf_max = (
        min(int(nf_max_declared), required_nf_max)
        if nf_max_declared is not None
        else required_nf_max
    )
    if nf_min_declared < 1 or nf_max < nf_min_declared:
        raise IndependentDomainError(
            f"invalid NF limits for {variable_id!r}"
        )

    # A total width W is realizable when some integer NF satisfies
    # finger_min <= W/NF <= finger_max.
    realizable_intervals: list[dict[str, Any]] = []
    for nf in range(nf_min_declared, nf_max + 1):
        interval_min = max(minimum, nf * finger_min)
        interval_max = min(maximum, nf * finger_max)
        if interval_min <= interval_max:
            realizable_intervals.append(
                {
                    "nf": nf,
                    "total_width_min_um": interval_min,
                    "total_width_max_um": interval_max,
                    "finger_width_min_um": interval_min / nf,
                    "finger_width_max_um": interval_max / nf,
                }
            )

    if not realizable_intervals:
        raise IndependentDomainError(
            f"declared total-width range for {variable_id!r} has no legal NF realization"
        )

    realizable_min = min(item["total_width_min_um"] for item in realizable_intervals)
    realizable_max = max(item["total_width_max_um"] for item in realizable_intervals)

    return {
        "domain_type": "technology_realizable_continuous_total_width",
        "candidate_values": [],
        "candidate_count": 0,
        "technology_minimum": realizable_min,
        "technology_maximum": realizable_max,
        "finger_width_min_um": finger_min,
        "finger_width_max_um": finger_max,
        "nf_min": min(item["nf"] for item in realizable_intervals),
        "nf_max": max(item["nf"] for item in realizable_intervals),
        "realizable_nf_intervals": realizable_intervals,
        "width_semantics": "total_effective_width",
        "scaling_model": finger_cfg.get(
            "scaling_model", "linear_current_scaling"
        ),
        "sampling": "deferred_to_assignment_synthesis",
    }


def _source_voltage(
    source_node: str,
    operating: Mapping[str, Any],
) -> float | None:
    node = source_node.lower()
    if node == "vss":
        return _optional_number(operating, "vss_v", "vss")
    if node == "vdd":
        return _optional_number(operating, "vdd_v", "vdd")
    return None


def _node_from_variable(variable_id: str) -> str:
    token = variable_id.lower()
    aliases = {"vout_v": "out", "output_v": "out", "vtail_v": "ntail"}
    if token in aliases:
        return aliases[token]
    if token.endswith("_v"):
        token = token[:-2]
    if token.startswith("v_"):
        token = token[2:]
    return token


def _node_voltage_domain(
    variable_id: str,
    model: Mapping[str, Any],
    devices: Mapping[str, Mapping[str, Any]],
    rows: Sequence[TechnologyRow],
    minimum: float,
    maximum: float,
) -> dict[str, Any]:
    node = _node_from_variable(variable_id)
    rules = model.get("project_inputs", {}).get("design_rules", {})
    operating = rules.get("operating_conditions", {})

    connected: list[dict[str, Any]] = []
    for name, device in devices.items():
        if str(device.get("kind", "")).lower() != "mos":
            continue
        terminals = device.get("terminals", {})
        if str(terminals.get("drain", "")).lower() != node:
            continue

        source_node = str(terminals.get("source", ""))
        source_voltage = _source_voltage(source_node, operating)
        if source_voltage is None:
            continue

        filters = _base_filters(model, device)
        polarity = filters["polarity"]
        values: list[float] = []
        records: list[dict[str, Any]] = []
        for item in rows:
            if not _row_matches(item.values, filters):
                continue
            vds = _optional_number(item.values, "vds_v", "vds_abs_v")
            if vds is None:
                continue
            value = (
                source_voltage + vds
                if polarity == "nmos"
                else source_voltage - vds
            )
            if minimum <= value <= maximum:
                values.append(value)
                records.append(
                    {
                        "technology_row_index": item.index,
                        "node_voltage_v": value,
                        "vds_abs_v": vds,
                    }
                )

        unique_values = _unique(values)
        if unique_values:
            connected.append(
                {
                    "device": name,
                    "polarity": polarity,
                    "minimum": min(unique_values),
                    "maximum": max(unique_values),
                    "sample_values": unique_values,
                    "supporting_row_count": len(records),
                    "records": records,
                }
            )

    if not connected:
        raise IndependentDomainError(
            f"no technology-backed drain domain for node {node!r}"
        )

    supported_minimum = max(
        minimum, *(item["minimum"] for item in connected)
    )
    supported_maximum = min(
        maximum, *(item["maximum"] for item in connected)
    )
    if supported_minimum > supported_maximum:
        raise IndependentDomainError(
            f"no common technology-supported interval for {variable_id!r}"
        )

    return {
        "domain_type": "technology_supported_continuous_interval",
        "candidate_values": [],
        "candidate_count": 0,
        "technology_minimum": supported_minimum,
        "technology_maximum": supported_maximum,
        "minimum": supported_minimum,
        "maximum": supported_maximum,
        "node": node,
        "device_domains": connected,
        "sampling": "deferred_to_assignment_synthesis",
    }


def build_independent_domains(
    compiled_model_path: Path,
    *,
    technology_csv_path: Path | None = None,
) -> Mapping[str, Any]:
    model = json.loads(compiled_model_path.read_text(encoding="utf-8"))
    if model.get("artifact") != "openams.compiled_circuit_model":
        raise IndependentDomainError(
            f"unsupported artifact {model.get('artifact')!r}"
        )

    technology_path = (
        technology_csv_path.resolve()
        if technology_csv_path is not None
        else _technology_path(compiled_model_path, model)
    )
    rows = load_technology_rows(technology_path)
    devices = _devices(model)
    rules = model.get("project_inputs", {}).get("design_rules", {})

    independent = (
        model.get("synthesis_interface", {}).get("independent_variables", [])
    )
    if not independent:
        raise IndependentDomainError("no independent variables declared")

    domains: dict[str, Any] = {}
    for item in independent:
        variable_id = str(item["id"])
        definition = item.get("original", {})
        if not isinstance(definition, Mapping):
            raise IndependentDomainError(
                f"{variable_id!r} has no mapping definition"
            )

        minimum, maximum, bound_sources = _effective_bounds(
            model, variable_id, definition
        )
        kind = str(definition.get("kind", "")).lower()
        device_name = _device_from_variable(variable_id)
        device = devices.get(device_name) if device_name else None

        if kind == "node_voltage":
            domain = _node_voltage_domain(
                variable_id, model, devices, rows, minimum, maximum
            )
        else:
            if device is None:
                raise IndependentDomainError(
                    f"cannot infer device context for {variable_id!r}"
                )
            filters = _base_filters(model, device)
            if kind == "total_width":
                domain = _total_width_domain(
                    variable_id,
                    definition,
                    rows,
                    filters,
                    rules,
                    minimum,
                    maximum,
                )
            else:
                domain = _technology_point_domain(
                    variable_id,
                    definition,
                    rows,
                    filters,
                    minimum,
                    maximum,
                )
            domain["device"] = device_name
            domain["filters"] = filters

        domains[variable_id] = {
            "id": variable_id,
            "kind": kind,
            "sampling_rule": definition.get("sampling"),
            "role": definition.get("role"),
            "declared_definition": dict(definition),
            "bound_sources": bound_sources,
            "declared_effective_minimum": minimum,
            "declared_effective_maximum": maximum,
            **domain,
        }

    return {
        "artifact": "openams.independent_variable_regions",
        "schema_version": 2,
        "status": "PASS",
        "circuit_name": model.get("circuit_name"),
        "compiled_model": str(compiled_model_path.resolve()),
        "technology_source": str(technology_path),
        "technology_row_count": len(rows),
        "general_rule": (
            "independent domain = design-intent request intersected with "
            "applicable rules, specifications, supplies, and technology support"
        ),
        "width_rule": (
            "total electrical width is design-intent controlled and may exceed "
            "one-finger width when an integer NF yields a legal finger width"
        ),
        "independent_variable_count": len(domains),
        "domains": domains,
        "next_stage": "derive_dependent_regions",
    }


def write_independent_domains(
    compiled_model_path: Path,
    output_path: Path,
    *,
    technology_csv_path: Path | None = None,
) -> Mapping[str, Any]:
    artifact = build_independent_domains(
        compiled_model_path,
        technology_csv_path=technology_csv_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return artifact

"""Assignment-synthesis Step 4: derive physically bounded correlated regions.

This module executes metadata-declared, topology-independent region primitives.

The final nonlinear relations and complete full-circuit assignment intersection
remain Step 5 responsibilities.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class DependentRegionError(ValueError):
    """Raised when a dependent region cannot be derived."""


@dataclass(frozen=True)
class TechRow:
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


def _num(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DependentRegionError(f"{name} must be numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise DependentRegionError(f"{name} must be finite: {value!r}")
    return result


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in ("", None):
            return row[name]
    raise DependentRegionError(f"missing fields {names!r}")


def load_rows(path: Path) -> tuple[TechRow, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = [
            TechRow(
                index=index,
                polarity=str(row["polarity"]).lower(),
                model=str(row["model"]),
                length_um=_num(row["length_um"], "length_um"),
                width_um=_num(row["width_um"], "width_um"),
                vgs_v=_num(_first(row, "vgs_v", "vgs_abs_v"), "vgs"),
                vds_v=_num(_first(row, "vds_v", "vds_abs_v"), "vds"),
                vbs_v=_num(_first(row, "vbs_v", "vbs_abs_v"), "vbs"),
                id_a=_num(_first(row, "id_abs_a", "id_a", "id"), "id"),
                vdsat_v=_num(
                    _first(row, "vdsat_abs_v", "vdsat_v", "vdsat"),
                    "vdsat",
                ),
                saturated=_truth(row.get("saturated", True)),
            )
            for index, row in enumerate(reader)
        ]
    if not rows:
        raise DependentRegionError(f"empty technology table: {path}")
    return tuple(rows)


def _interval(minimum: float, maximum: float) -> dict[str, float]:
    if minimum > maximum:
        raise DependentRegionError(f"empty interval [{minimum}, {maximum}]")
    return {"minimum": minimum, "maximum": maximum}


def _values_interval(values: Iterable[float], name: str) -> dict[str, float]:
    materialized = [float(value) for value in values]
    if not materialized:
        raise DependentRegionError(f"no values for {name}")
    return _interval(min(materialized), max(materialized))


def _intersect(*intervals: Mapping[str, Any]) -> dict[str, float]:
    return _interval(
        max(_num(item["minimum"], "minimum") for item in intervals),
        min(_num(item["maximum"], "maximum") for item in intervals),
    )


def _scale_interval(interval: Mapping[str, Any], scale: float) -> dict[str, float]:
    a = _num(interval["minimum"], "minimum") * scale
    b = _num(interval["maximum"], "maximum") * scale
    return _interval(min(a, b), max(a, b))


def _clip_interval(
    interval: Mapping[str, Any],
    minimum: float,
    maximum: float,
) -> dict[str, float]:
    return _intersect(interval, {"minimum": minimum, "maximum": maximum})


def _device_map(model: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for item in model["topology"]["devices"]:
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
    raise DependentRegionError(f"cannot infer polarity from {model_name!r}")


def _technology_path(model: Mapping[str, Any]) -> Path:
    path = model.get("technology", {}).get("source_path")
    if not path:
        raise DependentRegionError("compiled model has no technology source_path")
    return Path(path).resolve()


def _filtered_rows(
    rows: Sequence[TechRow],
    device: Mapping[str, Any],
    *,
    length_um: float,
    body_limit_v: float,
) -> tuple[TechRow, ...]:
    model_name = str(device["model"])
    polarity = _polarity(model_name)
    result = tuple(
        row
        for row in rows
        if row.model == model_name
        and row.polarity == polarity
        and math.isclose(row.length_um, length_um, rel_tol=0.0, abs_tol=1e-12)
        and row.saturated
        and abs(row.vbs_v) <= body_limit_v + 1e-15
        and row.id_a > 0.0
        and row.width_um > 0.0
    )
    if not result:
        raise DependentRegionError(f"no filtered rows for {model_name}")
    return result


def _width_policy(model: Mapping[str, Any]) -> dict[str, float]:
    intent = model["project_inputs"]["design_intent"]
    parameterization = intent["synthesis_parameterization"]
    policy = parameterization.get("dependent_width_realization", {})
    rules = model["project_inputs"]["design_rules"]["device_constraints"]["all_mos"]

    finger_min = _num(
        policy.get("finger_width_min_um", rules["width_min_um"]),
        "finger_width_min_um",
    )
    finger_max = _num(
        policy.get("finger_width_max_um", rules["width_max_um"]),
        "finger_width_max_um",
    )
    nf_min = int(policy.get("nf_min", 1))
    nf_max = int(policy.get("nf_max", 3))
    total_min = _num(
        policy.get("total_width_min_um", finger_min * nf_min),
        "total_width_min_um",
    )
    total_max = _num(
        policy.get("total_width_max_um", finger_max * nf_max),
        "total_width_max_um",
    )
    return {
        "finger_min_um": finger_min,
        "finger_max_um": finger_max,
        "nf_min": nf_min,
        "nf_max": nf_max,
        "total_min_um": total_min,
        "total_max_um": total_max,
    }


def _legal_total_width(width_um: float, policy: Mapping[str, Any]) -> bool:
    if not (policy["total_min_um"] <= width_um <= policy["total_max_um"]):
        return False
    return any(
        policy["finger_min_um"] <= width_um / nf <= policy["finger_max_um"]
        for nf in range(int(policy["nf_min"]), int(policy["nf_max"]) + 1)
    )


def _minimum_nf(width_um: float, policy: Mapping[str, Any]) -> int | None:
    for nf in range(int(policy["nf_min"]), int(policy["nf_max"]) + 1):
        finger = width_um / nf
        if policy["finger_min_um"] <= finger <= policy["finger_max_um"]:
            return nf
    return None


def _required_total_width(row: TechRow, target_current_a: float) -> float:
    return row.width_um * target_current_a / row.id_a


def _row_can_realize_current_interval(
    row: TechRow,
    current: Mapping[str, Any],
    width: Mapping[str, Any],
) -> bool:
    current_min = _num(current["minimum"], "current.minimum")
    current_max = _num(current["maximum"], "current.maximum")
    width_min = _num(width["minimum"], "width.minimum")
    width_max = _num(width["maximum"], "width.maximum")
    scaled_min = row.id_a * width_min / row.width_um
    scaled_max = row.id_a * width_max / row.width_um
    return max(current_min, scaled_min) <= min(current_max, scaled_max)


def _derived_width_interval(
    rows: Sequence[TechRow],
    current: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    widths = []
    evidence = []
    for row in rows:
        for target in (
            _num(current["minimum"], "current.minimum"),
            _num(current["maximum"], "current.maximum"),
        ):
            width = _required_total_width(row, target)
            nf = _minimum_nf(width, policy)
            if nf is not None:
                widths.append(width)
                evidence.append(
                    {
                        "technology_row_index": row.index,
                        "target_current_a": target,
                        "required_total_width_um": width,
                        "nf": nf,
                        "finger_width_um": width / nf,
                        "vgs_v": row.vgs_v,
                        "vds_v": row.vds_v,
                    }
                )
    if not widths:
        raise DependentRegionError("no legal derived width")
    return {
        **_values_interval(widths, "derived width"),
        "width_semantics": "total_effective_width",
        "scaling_model": "linear_current_scaling",
        "evidence_count": len(evidence),
        "evidence": evidence,
    }


def _domain_interval(domain: Mapping[str, Any]) -> dict[str, float]:
    minimum = domain.get("technology_minimum", domain.get("minimum"))
    maximum = domain.get("technology_maximum", domain.get("maximum"))
    if minimum is None or maximum is None:
        minimum = domain.get("declared_effective_minimum")
        maximum = domain.get("declared_effective_maximum")
    return _interval(
        _num(minimum, "domain minimum"),
        _num(maximum, "domain maximum"),
    )


def _candidate_current_interval(domain: Mapping[str, Any]) -> dict[str, float]:
    values = domain.get("candidate_values") or []
    return _values_interval(values, "candidate currents") if values else _domain_interval(domain)


def _execute_group_primitive(
    model: Mapping[str, Any],
    independent: Mapping[str, Any],
    rows: Sequence[TechRow],
    group: Mapping[str, Any],
    completed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    solver_type = str(group.get("solver_type", group.get("solver", "")))
    if solver_type == "generic_dependency_graph":
        raise DependentRegionError("generic_dependency_graph is executed as a whole-plan solver")

    from .generic_region_primitives import PRIMITIVES
    primitive = PRIMITIVES.get(solver_type)
    if primitive is None:
        raise DependentRegionError(f"unknown generic region primitive {solver_type!r}")

    dependencies = list(group.get("depends_on", []))
    if not dependencies:
        return primitive(model, independent, rows, group)
    if len(dependencies) != 1 or dependencies[0] not in completed:
        raise DependentRegionError(
            f"group {group.get('id')!r} has unresolved dependencies {dependencies!r}"
        )
    return primitive(model, independent, completed[dependencies[0]], rows, group)


def build_dependent_regions(
    compiled_model_path: Path,
    independent_regions_path: Path,
) -> Mapping[str, Any]:
    model = json.loads(compiled_model_path.read_text(encoding="utf-8"))
    independent = json.loads(independent_regions_path.read_text(encoding="utf-8"))
    rows = load_rows(_technology_path(model))

    groups = model["project_inputs"]["design_intent"]["assignment_synthesis"]["groups"]
    completed: dict[str, dict[str, Any]] = {}
    ordered_results: list[dict[str, Any]] = []

    whole_plan_generic = all(
        str(group.get("solver_type", group.get("solver", ""))) == "generic_dependency_graph"
        for group in groups
    )
    if whole_plan_generic:
        from .generic_dependency import build_generic_group_results
        ordered_results, generic_regions, deferred = build_generic_group_results(
            model, independent, rows
        )
    else:
        deferred = []
        generic_regions = {}
        for group in groups:
            result = _execute_group_primitive(
                model, independent, rows, group, completed
            )
            group_id = str(group["id"])
            completed[group_id] = result
            ordered_results.append(result)

    all_regions: dict[str, Any] = dict(generic_regions)
    for result in ordered_results:
        all_regions.update(result["dependent_regions"])

    declared = {
        item["id"] for item in model["synthesis_interface"]["dependent_quantities"]
    }
    derived = set(all_regions)
    missing = sorted(declared - derived)
    extra = sorted(derived - declared)

    return {
        "artifact": "openams.dependent_variable_regions",
        "schema_version": 3,
        "status": "PASS" if not missing else "FAIL",
        "circuit_name": model["circuit_name"],
        "compiled_model": str(compiled_model_path.resolve()),
        "independent_regions": str(independent_regions_path.resolve()),
        "technology_source": str(_technology_path(model)),
        "groups": ordered_results,
        "dependent_regions": all_regions,
        "declared_dependent_quantities": sorted(declared),
        "derived_dependent_quantities": sorted(derived),
        "missing_declared_quantities": missing,
        "additional_derived_quantities": extra,
        "deferred_correlations": deferred,
        "resolution_semantics": "metadata_declared_generic_region_primitives",
        "next_stage": "intersect_complete_dc_assignments",
    }


def write_dependent_regions(
    compiled_model_path: Path,
    independent_regions_path: Path,
    output_path: Path,
) -> Mapping[str, Any]:
    artifact = build_dependent_regions(
        compiled_model_path,
        independent_regions_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return artifact

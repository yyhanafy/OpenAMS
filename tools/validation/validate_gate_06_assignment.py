#!/usr/bin/env python3
"""Gate 6: build one real-table-backed simulation-ready assignment.

The validator:
1. loads the active SKY130 characterization table;
2. searches saturated real rows for a correlated M1..M7 candidate;
3. enforces technology current tolerances and the second-stage width rule;
4. executes the production HierarchicalSynthesisWorkflow;
5. emits a production FixedAssignmentBatch and direct-simulation plan.

Topology current fields are nominal circuit currents. The evidence also retains
the measured table currents and their relative errors.
"""

from __future__ import annotations

import argparse
import bisect
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openams.adapters import load_characterization_table_csv
from openams.io import load_yaml_mapping
from openams.metadata import normalize_project_inputs
from openams.planning import ExecutionRoute
from openams.synthesis import (
    CanonicalConstraintRecord,
    CircuitRegionAssignmentEmitter,
    HierarchicalSynthesisWorkflow,
    RegionBinding,
    RegionInput,
    SynthesisStage,
)
from openams.technology import DevicePolarity, OperatingRegion, TechnologyQuantity


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--input-dir",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs"),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/validation/evidence/gate_06_assignment"),
    )
    return p.parse_args()


def rel_error(actual: float, target: float, abs_tol: float) -> float:
    return abs(actual - target) / max(abs(target), abs_tol)


def point_row(point) -> dict[str, float]:
    op = point.operating_point
    values = point.values
    return {
        "id_measured_a": float(values[TechnologyQuantity.ID]),
        "width_um": op.width_m * 1e6,
        "length_um": op.length_m * 1e6,
        "vgs_v": op.vgs_v,
        "vds_v": op.vds_v,
        "vbs_v": op.vbs_v,
        "gm_s": float(values.get(TechnologyQuantity.GM, 0.0)),
        "gds_s": float(values.get(TechnologyQuantity.GDS, 0.0)),
        "vth_v": float(values.get(TechnologyQuantity.VTH, 0.0)),
        "vdsat_v": float(values.get(TechnologyQuantity.VDSAT, 0.0)),
    }


def nearest(sorted_points, currents, target):
    index = bisect.bisect_left(currents, target)
    candidates = []
    for candidate in (index - 1, index, index + 1):
        if 0 <= candidate < len(sorted_points):
            candidates.append(sorted_points[candidate])
    return min(
        candidates,
        key=lambda point: abs(
            float(point.values[TechnologyQuantity.ID]) - target
        ),
    )


def select_candidate(table, rules):
    saturated = [
        point for point in table.points
        if point.region is OperatingRegion.SATURATION
        and TechnologyQuantity.ID in point.values
    ]
    nmos = sorted(
        [p for p in saturated if p.operating_point.model.polarity is DevicePolarity.NMOS],
        key=lambda p: float(p.values[TechnologyQuantity.ID]),
    )
    pmos = sorted(
        [p for p in saturated if p.operating_point.model.polarity is DevicePolarity.PMOS],
        key=lambda p: float(p.values[TechnologyQuantity.ID]),
    )
    ncurr = [float(p.values[TechnologyQuantity.ID]) for p in nmos]
    pcurr = [float(p.values[TechnologyQuantity.ID]) for p in pmos]

    tech = rules["technology_intersection"]
    rel_tol = float(tech["current_relative_tolerance"])
    abs_tol = float(tech["current_absolute_tolerance_a"])
    width_tol = float(tech["width_relation_relative_tolerance"])

    candidates = []
    # Prefer useful currents rather than near-zero leakage points.
    for m1 in nmos:
        i1 = float(m1.values[TechnologyQuantity.ID])
        if i1 < 1e-6:
            continue
        m3 = nearest(pmos, pcurr, i1)
        m5 = nearest(nmos, ncurr, 2.0 * i1)
        e3 = rel_error(float(m3.values[TechnologyQuantity.ID]), i1, abs_tol)
        e5 = rel_error(float(m5.values[TechnologyQuantity.ID]), 2.0 * i1, abs_tol)
        if e3 <= rel_tol and e5 <= rel_tol:
            candidates.append((e3 + e5, m1, m3, m5))
    if not candidates:
        raise SystemExit("no input/bias candidate satisfies configured current tolerances")

    # Keep search bounded and deterministic.
    for _, m1, m3, m5 in sorted(candidates, key=lambda item: item[0])[:100]:
        w3 = m3.operating_point.width_m
        w5 = m5.operating_point.width_m

        for m7 in nmos:
            i7 = float(m7.values[TechnologyQuantity.ID])
            if i7 < 1e-6:
                continue
            # Width rule: w6/w3 == 2*w7/w5.
            required_w6 = 2.0 * m7.operating_point.width_m * w3 / w5
            width_matches = [
                p for p in pmos
                if abs(p.operating_point.width_m - required_w6)
                / max(abs(required_w6), 1e-30) <= width_tol
            ]
            if not width_matches:
                continue
            m6 = min(
                width_matches,
                key=lambda p: abs(float(p.values[TechnologyQuantity.ID]) - i7),
            )
            e67 = rel_error(float(m6.values[TechnologyQuantity.ID]), i7, abs_tol)
            if e67 <= rel_tol:
                return m1, m3, m5, m6, m7

    raise SystemExit(
        "no complete M1..M7 candidate satisfies current tolerances and "
        "the configured second-stage width relation"
    )


def binding(name: str, point, nominal_current: float) -> RegionBinding:
    row = point_row(point)
    row["current_a"] = nominal_current
    return RegionBinding(
        name,
        RegionInput(name, (row,), metadata={"source": point.source}),
        {
            f"device.{name}.current": "current_a",
            f"device.{name}.width": "width_um",
            f"device.{name}.length": "length_um",
            f"device.{name}.vgs": "vgs_v",
            f"device.{name}.vds": "vds_v",
            f"device.{name}.vbs": "vbs_v",
            f"device.{name}.gm": "gm_s",
            f"device.{name}.gds": "gds_s",
            f"device.{name}.vth": "vth_v",
            f"device.{name}.vdsat": "vdsat_v",
            f"device.{name}.measured_current": "id_measured_a",
        },
    )


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    specs = load_yaml_mapping(args.input_dir / "specs.yaml")
    intent = load_yaml_mapping(args.input_dir / "design_intent.yaml")
    rules = load_yaml_mapping(args.input_dir / "design_rules.yaml")
    simulation = load_yaml_mapping(args.input_dir / "simulation.yaml")
    project = normalize_project_inputs(
        specifications=specs,
        design_intent=intent,
        design_rules=rules,
        simulation=simulation,
    )

    source = (args.input_dir / project.technology.active.source).resolve()
    table = load_characterization_table_csv(
        source,
        technology_name=project.technology.active_source,
    )

    m1, m3, m5, m6, m7 = select_candidate(table, rules)
    i1 = float(m1.values[TechnologyQuantity.ID])
    i7 = float(m7.values[TechnologyQuantity.ID])

    bindings = (
        binding("M1", m1, i1),
        binding("M2", m1, i1),
        binding("M3", m3, i1),
        binding("M4", m3, i1),
        binding("M5", m5, 2.0 * i1),
        binding("M6", m6, i7),
        binding("M7", m7, i7),
    )

    stages = (
        SynthesisStage(
            "input_pair",
            ("M1", "M2"),
            (
                CanonicalConstraintRecord(
                    "input_current_match",
                    "device.M1.current == device.M2.current",
                ),
                CanonicalConstraintRecord(
                    "input_width_match",
                    "device.M1.width == device.M2.width",
                ),
            ),
        ),
        SynthesisStage(
            "active_load",
            ("M3", "M4"),
            (
                CanonicalConstraintRecord(
                    "load_current_match",
                    "device.M3.current == device.M4.current",
                ),
                CanonicalConstraintRecord(
                    "load_width_match",
                    "device.M3.width == device.M4.width",
                ),
            ),
        ),
        SynthesisStage(
            "output_stage",
            ("M6", "M7"),
            (
                CanonicalConstraintRecord(
                    "output_current_match",
                    "device.M6.current == device.M7.current",
                ),
            ),
        ),
        SynthesisStage(
            "full_circuit",
            ("input_pair", "active_load", "M5", "output_stage"),
            (
                CanonicalConstraintRecord(
                    "tail_kcl",
                    "device.M5.current == device.M1.current + device.M2.current",
                    kind="topology_derived",
                    source="topology",
                ),
                CanonicalConstraintRecord(
                    "load_tracks_input",
                    "device.M3.current == device.M1.current",
                ),
            ),
            metadata={"topology": "two_stage_opamp", "technology": table.identity.name},
        ),
    )

    result = HierarchicalSynthesisWorkflow(reject_empty_stage=True).run(
        bindings,
        stages,
    )

    final_map = dict(result.final.output_binding.field_map)
    batch = CircuitRegionAssignmentEmitter().emit(
        result.final.region,
        final_map,
        required_variables=tuple(final_map),
    )
    record = batch.records[0]

    selected = {
        name: point_row(point)
        for name, point in {
            "M1": m1, "M2": m1, "M3": m3, "M4": m3,
            "M5": m5, "M6": m6, "M7": m7,
        }.items()
    }
    selected["M1"]["nominal_current_a"] = i1
    selected["M2"]["nominal_current_a"] = i1
    selected["M3"]["nominal_current_a"] = i1
    selected["M4"]["nominal_current_a"] = i1
    selected["M5"]["nominal_current_a"] = 2.0 * i1
    selected["M6"]["nominal_current_a"] = i7
    selected["M7"]["nominal_current_a"] = i7

    tech = rules["technology_intersection"]
    errors = {
        "M3_vs_M1": rel_error(selected["M3"]["id_measured_a"], i1, tech["current_absolute_tolerance_a"]),
        "M5_vs_2M1": rel_error(selected["M5"]["id_measured_a"], 2.0*i1, tech["current_absolute_tolerance_a"]),
        "M6_vs_M7": rel_error(selected["M6"]["id_measured_a"], i7, tech["current_absolute_tolerance_a"]),
    }
    width_lhs = selected["M6"]["width_um"] / selected["M3"]["width_um"]
    width_rhs = 2.0 * selected["M7"]["width_um"] / selected["M5"]["width_um"]
    errors["second_stage_width_relation"] = abs(width_lhs-width_rhs)/max(abs(width_rhs),1e-30)

    checks = {
        "four_stages_executed": len(result.stages) == 4,
        "final_region_has_one_row": result.final.retained_count == 1,
        "one_assignment_emitted": batch.count == 1,
        "assignment_is_simulation_ready": record.assignment.status.value == "simulation_ready",
        "route_is_direct_simulation": record.plan.route is ExecutionRoute.DIRECT_SIMULATION,
        "all_current_errors_within_tolerance": all(
            errors[name] <= float(tech["current_relative_tolerance"])
            for name in ("M3_vs_M1", "M5_vs_2M1", "M6_vs_M7")
        ),
        "width_relation_within_tolerance": (
            errors["second_stage_width_relation"]
            <= float(tech["width_relation_relative_tolerance"])
        ),
    }
    passed = all(checks.values())

    summary = {
        "gate": 6,
        "status": "PASS" if passed else "FAIL",
        "source": str(source),
        "stage_counts": {
            item.stage.name: item.retained_count for item in result.stages
        },
        "selected_rows": selected,
        "relation_errors": errors,
        "assignment": {
            "name": record.assignment.name,
            "status": record.assignment.status.value,
            "values": dict(record.assignment.values),
            "route": record.plan.route.value,
            "stages": [stage.value for stage in record.plan.stages],
            "source_indices": dict(record.source_indices),
        },
        "checks": checks,
    }

    (args.output_dir / "assignment_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "assignment.json").write_text(
        json.dumps(summary["assignment"], indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "ASSIGNMENT_REPORT.md").write_text(
        "# Gate 6 Assignment Validation\n\n"
        f"- **Status:** {summary['status']}\n"
        f"- **Stages:** {summary['stage_counts']}\n"
        f"- **Assignments:** {batch.count}\n"
        f"- **Route:** `{record.plan.route.value}`\n\n"
        "## Checks\n\n```json\n"
        + json.dumps(checks, indent=2)
        + "\n```\n\n## Relation Errors\n\n```json\n"
        + json.dumps(errors, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )

    print("===== OPENAMS GATE 6: ASSIGNMENT SYNTHESIS =====")
    print(f"status:       {summary['status']}")
    print(f"stages:       {summary['stage_counts']}")
    print(f"assignments:  {batch.count}")
    print(f"route:        {record.plan.route.value}")
    print(f"evidence:     {args.output_dir}")
    if not passed:
        for name, value in checks.items():
            if not value:
                print(f"[FAIL] {name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

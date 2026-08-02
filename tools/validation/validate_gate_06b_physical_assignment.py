#!/usr/bin/env python3
"""Gate 6B: find one physically consistent two-stage-op-amp assignment.

All seven transistor operating points are derived from one shared node set:
VDD, VSS, VIN_CM, VTAIL, N1=N2, VBIAS, and VOUT.

Measured characterization-table currents are used directly. No nominal current
substitution is allowed.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from openams.adapters import load_characterization_table_csv
from openams.io import load_yaml_mapping
from openams.metadata import normalize_project_inputs
from openams.planning import ExecutionRoute
from openams.synthesis import (
    CircuitRegion,
    CircuitRegionAssignmentEmitter,
    CircuitRow,
    RegionInput,
)
from openams.technology import DevicePolarity, OperatingRegion, TechnologyQuantity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs"),
    )
    parser.add_argument(
        "--technology-csv",
        type=Path,
        default=None,
        help="Override the technology CSV selected by metadata.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "docs/validation/evidence/gate_06b_physical_assignment"
        ),
    )
    return parser.parse_args()


def q(value: float) -> float:
    return round(float(value), 9)


def rel_error(actual: float, target: float, abs_tol: float) -> float:
    return abs(actual - target) / max(abs(target), abs_tol)


def point_payload(point) -> dict[str, Any]:
    op = point.operating_point
    return {
        "model": op.model.name,
        "polarity": op.model.polarity.value,
        "length_um": op.length_m * 1e6,
        "width_um": op.width_m * 1e6,
        "vgs_abs_v": op.vgs_v,
        "vds_abs_v": op.vds_v,
        "vbs_abs_v": op.vbs_v,
        "id_abs_a": float(point.values[TechnologyQuantity.ID]),
        "gm_s": float(point.values.get(TechnologyQuantity.GM, 0.0)),
        "gds_s": float(point.values.get(TechnologyQuantity.GDS, 0.0)),
        "vth_abs_v": float(point.values.get(TechnologyQuantity.VTH, 0.0)),
        "vdsat_abs_v": float(point.values.get(TechnologyQuantity.VDSAT, 0.0)),
        "region": point.region.value,
        "source": point.source,
    }


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

    source = (
        args.technology_csv.resolve()
        if args.technology_csv is not None
        else (args.input_dir / project.technology.active.source).resolve()
    )
    table = load_characterization_table_csv(
        source,
        technology_name=project.technology.active_source,
    )

    op_rules = rules["operating_conditions"]
    tech_rules = rules["technology_intersection"]
    device_rules = rules["device_constraints"]["all_mos"]

    vdd = float(op_rules["vdd_v"])
    vss = float(op_rules["vss_v"])
    vin = float(op_rules["vin_cm_v"])
    rel_tol = float(tech_rules["current_relative_tolerance"])
    abs_tol = float(tech_rules["current_absolute_tolerance_a"])
    node_tol = float(tech_rules["node_voltage_tolerance_v"])
    diode_tol = float(tech_rules["diode_voltage_tolerance_v"])
    width_tol = float(tech_rules["width_relation_relative_tolerance"])
    length_um = float(device_rules["length_um"])
    width_min = float(device_rules["width_min_um"])
    width_max = float(device_rules["width_max_um"])

    saturated = [
        point
        for point in table.points
        if point.region is OperatingRegion.SATURATION
        and TechnologyQuantity.ID in point.values
        and abs(point.operating_point.length_m * 1e6 - length_um) <= 1e-12
        and width_min <= point.operating_point.width_m * 1e6 <= width_max
    ]

    nmos = [
        p for p in saturated
        if p.operating_point.model.polarity is DevicePolarity.NMOS
    ]
    pmos = [
        p for p in saturated
        if p.operating_point.model.polarity is DevicePolarity.PMOS
    ]

    # Build indexed subsets so the dense table can be searched without
    # evaluating a full NMOS × PMOS Cartesian product.
    nmos_body_zero = [
        p for p in nmos if abs(p.operating_point.vbs_v) <= node_tol
    ]
    pmos_body_zero = [
        p for p in pmos if abs(p.operating_point.vbs_v) <= node_tol
    ]
    diode_pmos = [
        p for p in pmos_body_zero
        if abs(p.operating_point.vgs_v - p.operating_point.vds_v) <= diode_tol
    ]

    nmos_by_vds = defaultdict(list)
    nmos_by_vgs = defaultdict(list)
    pmos_by_vgs_vds = defaultdict(list)

    bucket = max(node_tol, 1e-6)

    def b(value: float) -> int:
        return round(float(value) / bucket)

    def nearby(index, *values):
        keys = [b(value) for value in values]
        if len(keys) == 1:
            for delta in (-1, 0, 1):
                yield from index.get((keys[0] + delta,), ())
        elif len(keys) == 2:
            for d0 in (-1, 0, 1):
                for d1 in (-1, 0, 1):
                    yield from index.get((keys[0] + d0, keys[1] + d1), ())
        else:
            raise ValueError("unsupported lookup dimensionality")

    for point in nmos_body_zero:
        op = point.operating_point
        nmos_by_vds[(b(op.vds_v),)].append(point)
        nmos_by_vgs[(b(op.vgs_v),)].append(point)

    for point in pmos_body_zero:
        op = point.operating_point
        pmos_by_vgs_vds[(b(op.vgs_v), b(op.vds_v))].append(point)

    # Candidate M1 rows determine VTAIL and, with a diode-connected M3 row,
    # determine N1. Balanced input operation uses N2=N1.
    physical_candidates = []
    rejections = {
        "m1_tail_or_body": 0,
        "m3_not_diode_connected": 0,
        "m1_vds_mismatch": 0,
        "m3_current_mismatch": 0,
        "no_m5_coordinate": 0,
        "m5_current_mismatch": 0,
        "no_m7_coordinate": 0,
        "no_m6_coordinate": 0,
        "m6_m7_current_mismatch": 0,
        "width_relation_mismatch": 0,
    }

    for m1 in nmos:
        op1 = m1.operating_point
        i1 = float(m1.values[TechnologyQuantity.ID])
        if i1 < 1e-6:
            continue

        vtail = vin - op1.vgs_v
        if vtail < vss - node_tol or vtail > vin + node_tol:
            rejections["m1_tail_or_body"] += 1
            continue
        if abs(op1.vbs_v - abs(vss - vtail)) > node_tol:
            rejections["m1_tail_or_body"] += 1
            continue

        for m3 in diode_pmos:
            op3 = m3.operating_point

            # M3 is diode connected: |VSG| = |VSD|.
            if abs(op3.vgs_v - op3.vds_v) > diode_tol:
                rejections["m3_not_diode_connected"] += 1
                continue
            if abs(op3.vbs_v) > node_tol:
                continue

            n1 = vdd - op3.vgs_v
            n2 = n1

            expected_m1_vds = n1 - vtail
            if abs(op1.vds_v - expected_m1_vds) > node_tol:
                rejections["m1_vds_mismatch"] += 1
                continue

            i3 = float(m3.values[TechnologyQuantity.ID])
            e31 = rel_error(i3, i1, abs_tol)
            if e31 > rel_tol:
                rejections["m3_current_mismatch"] += 1
                continue

            # M5: VGS=VBIAS, VDS=VTAIL, VBS=0. VBIAS is free, so
            # query all body-zero NMOS rows near the required VDS.
            m5_candidates = [
                p for p in nearby(nmos_by_vds, vtail)
                if abs(p.operating_point.vds_v - vtail) <= node_tol
            ]

            if not m5_candidates:
                rejections["no_m5_coordinate"] += 1

            for m5 in m5_candidates:
                op5 = m5.operating_point
                i5 = float(m5.values[TechnologyQuantity.ID])
                e5 = rel_error(i5, 2.0 * i1, abs_tol)
                if e5 > rel_tol:
                    rejections["m5_current_mismatch"] += 1
                    continue

                vbias = vss + op5.vgs_v

                # VOUT comes from the declared independent-variable range.
                vout_cfg = intent["synthesis_parameterization"]["independent_variables"]["vout_v"]
                vout_min = float(vout_cfg["minimum"])
                vout_max = float(vout_cfg["maximum"])

                # M7: VGS=VBIAS, VDS=VOUT, VBS=0.
                m7_candidates = [
                    p for p in nearby(nmos_by_vgs, vbias - vss)
                    if abs(p.operating_point.vgs_v - (vbias - vss)) <= node_tol
                    and vout_min - node_tol <= p.operating_point.vds_v <= vout_max + node_tol
                ]

                if not m7_candidates:
                    rejections["no_m7_coordinate"] += 1

                for m7 in m7_candidates:
                    op7 = m7.operating_point
                    vout = vss + op7.vds_v
                    if not (vout_min - node_tol <= vout <= vout_max + node_tol):
                        continue

                    # M6: VSG=VDD-N2, VSD=VDD-VOUT, VBS=0.
                    expected_vsg6 = vdd - n2
                    expected_vsd6 = vdd - vout

                    m6_candidates = [
                        p for p in nearby(
                            pmos_by_vgs_vds,
                            expected_vsg6,
                            expected_vsd6,
                        )
                        if abs(p.operating_point.vgs_v - expected_vsg6) <= node_tol
                        and abs(p.operating_point.vds_v - expected_vsd6) <= node_tol
                    ]

                    if not m6_candidates:
                        rejections["no_m6_coordinate"] += 1

                    for m6 in m6_candidates:
                        i6 = float(m6.values[TechnologyQuantity.ID])
                        i7 = float(m7.values[TechnologyQuantity.ID])
                        e67 = rel_error(i6, i7, abs_tol)
                        if e67 > rel_tol:
                            rejections["m6_m7_current_mismatch"] += 1
                            continue

                        w3 = m3.operating_point.width_m
                        w5 = m5.operating_point.width_m
                        w6 = m6.operating_point.width_m
                        w7 = m7.operating_point.width_m
                        lhs = w6 / w3
                        rhs = 2.0 * w7 / w5
                        ewidth = abs(lhs - rhs) / max(abs(rhs), 1e-30)
                        if ewidth > width_tol:
                            rejections["width_relation_mismatch"] += 1
                            continue

                        score = e31 + e5 + e67 + ewidth
                        physical_candidates.append(
                            (
                                score,
                                {
                                    "M1": m1,
                                    "M2": m1,
                                    "M3": m3,
                                    "M4": m3,
                                    "M5": m5,
                                    "M6": m6,
                                    "M7": m7,
                                },
                                {
                                    "vdd_v": vdd,
                                    "vss_v": vss,
                                    "vin_cm_v": vin,
                                    "vtail_v": vtail,
                                    "n1_v": n1,
                                    "n2_v": n2,
                                    "vbias_v": vbias,
                                    "vout_v": vout,
                                },
                                {
                                    "m3_vs_m1": e31,
                                    "m5_vs_m1_plus_m2": e5,
                                    "m6_vs_m7": e67,
                                    "second_stage_width_relation": ewidth,
                                },
                            )
                        )

    if not physical_candidates:
        summary = {
            "gate": "6B",
            "status": "NO_PHYSICAL_ASSIGNMENT_FOUND",
            "source": str(source),
            "searched_saturated_points": len(saturated),
            "nmos_points": len(nmos),
            "pmos_points": len(pmos),
            "diode_pmos_points": len(diode_pmos),
            "nmos_body_zero_points": len(nmos_body_zero),
            "pmos_body_zero_points": len(pmos_body_zero),
            "tolerances": {
                "current_relative": rel_tol,
                "current_absolute_a": abs_tol,
                "node_voltage_v": node_tol,
                "diode_voltage_v": diode_tol,
                "width_relative": width_tol,
            },
            "rejection_counts": rejections,
            "conclusion": (
                "The smoke table contains no complete assignment satisfying "
                "shared-node voltage equations, measured-current KCL, saturation, "
                "and the second-stage width relation."
            ),
        }
        (args.output_dir / "physical_assignment_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        print("===== OPENAMS GATE 6B: PHYSICAL ASSIGNMENT =====")
        print("status: NO_PHYSICAL_ASSIGNMENT_FOUND")
        print(f"searched: {len(saturated)} saturated points")
        print("rejections:")
        for name, count in rejections.items():
            print(f"  {name}: {count}")
        print(f"evidence: {args.output_dir}")
        return 2

    score, selected, nodes, errors = min(
        physical_candidates,
        key=lambda item: item[0],
    )

    values = dict(nodes)
    for name, point in selected.items():
        payload = point_payload(point)
        prefix = f"device.{name}"
        values.update(
            {
                f"{prefix}.width": payload["width_um"],
                f"{prefix}.length": payload["length_um"],
                f"{prefix}.current": payload["id_abs_a"],
                f"{prefix}.vgs": payload["vgs_abs_v"],
                f"{prefix}.vds": payload["vds_abs_v"],
                f"{prefix}.vbs": payload["vbs_abs_v"],
                f"{prefix}.gm": payload["gm_s"],
                f"{prefix}.gds": payload["gds_s"],
                f"{prefix}.vth": payload["vth_abs_v"],
                f"{prefix}.vdsat": payload["vdsat_abs_v"],
            }
        )

    row = CircuitRow(values=values, source_indices={name: 0 for name in selected})
    region = CircuitRegion(
        inputs=(RegionInput("physical_assignment", (values,)),),
        rows=(row,),
        rejected=(),
        constraint_names=(
            "shared_node_voltage_equations",
            "measured_current_kcl",
            "second_stage_width_relation",
            "saturation",
        ),
        metadata={
            "source": str(source),
            "physical_consistency": True,
            "candidate_score": score,
        },
    )

    mapping = {name: name for name in values}
    batch = CircuitRegionAssignmentEmitter().emit(
        region,
        mapping,
        required_variables=tuple(mapping),
    )
    record = batch.records[0]

    selected_payload = {
        name: point_payload(point) for name, point in selected.items()
    }

    checks = {
        "one_physical_candidate_selected": True,
        "shared_nodes_present": set(nodes) == {
            "vdd_v", "vss_v", "vin_cm_v", "vtail_v",
            "n1_v", "n2_v", "vbias_v", "vout_v",
        },
        "all_devices_saturated": all(
            point.region is OperatingRegion.SATURATION
            for point in selected.values()
        ),
        "measured_current_errors_within_tolerance": all(
            errors[name] <= rel_tol
            for name in ("m3_vs_m1", "m5_vs_m1_plus_m2", "m6_vs_m7")
        ),
        "width_relation_within_tolerance": (
            errors["second_stage_width_relation"] <= width_tol
        ),
        "assignment_is_simulation_ready": (
            record.assignment.status.value == "simulation_ready"
        ),
        "route_is_direct_simulation": (
            record.plan.route is ExecutionRoute.DIRECT_SIMULATION
        ),
    }

    summary = {
        "gate": "6B",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "source": str(source),
        "candidate_score": score,
        "nodes": nodes,
        "devices": selected_payload,
        "relation_errors": errors,
        "assignment": {
            "name": record.assignment.name,
            "status": record.assignment.status.value,
            "route": record.plan.route.value,
            "values": dict(record.assignment.values),
        },
        "checks": checks,
    }

    (args.output_dir / "physical_assignment_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "physical_assignment.json").write_text(
        json.dumps(summary["assignment"], indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "PHYSICAL_ASSIGNMENT_REPORT.md").write_text(
        "# Gate 6B Physical Assignment Validation\n\n"
        f"- **Status:** {summary['status']}\n"
        f"- **Candidate score:** {score}\n"
        f"- **Route:** `{record.plan.route.value}`\n\n"
        "## Shared Nodes\n\n```json\n"
        + json.dumps(nodes, indent=2)
        + "\n```\n\n## Relation Errors\n\n```json\n"
        + json.dumps(errors, indent=2)
        + "\n```\n\n## Checks\n\n```json\n"
        + json.dumps(checks, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )

    print("===== OPENAMS GATE 6B: PHYSICAL ASSIGNMENT =====")
    print(f"status:       {summary['status']}")
    print(f"nodes:        {nodes}")
    print(f"route:        {record.plan.route.value}")
    print(f"evidence:     {args.output_dir}")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

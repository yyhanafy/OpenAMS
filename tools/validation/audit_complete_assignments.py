#!/usr/bin/env python3
"""Audit OpenAMS Step 5 complete assignments for reality, uniqueness, and correctness."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


def f(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite value: {value!r}")
    return result


def close(a: float, b: float, *, rtol: float, atol: float) -> bool:
    return abs(a - b) <= max(atol, rtol * max(abs(a), abs(b), 1e-30))


def q(value: Any, digits: int = 12) -> float:
    return round(f(value), digits)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def canonical_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    fields = (
        "i_m5_a",
        "w_m1_um",
        "vout_v",
        "vtail_v",
        "n1_v",
        "n2_v",
        "vbias_v",
        "w_m3_um",
        "w_m5_um",
        "w_m6_um",
        "w_m7_um",
        "i_m6_a",
        "m1_technology_row_index",
        "m3_technology_row_index",
        "m4_technology_row_index",
        "m5_technology_row_index",
        "m6_lower_technology_row_index",
        "m6_upper_technology_row_index",
        "m7_technology_row_index",
    )
    result = []
    for name in fields:
        value = row[name]
        if "row_index" in name:
            result.append(int(value))
        else:
            result.append(q(value))
    return tuple(result)


def assignment_equivalence_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Physical assignment key ignoring provenance and assignment ID."""
    fields = (
        "i_m1_a", "i_m2_a", "i_m3_a", "i_m4_a", "i_m5_a", "i_m6_a", "i_m7_a",
        "w_m1_um", "w_m2_um", "w_m3_um", "w_m4_um", "w_m5_um", "w_m6_um", "w_m7_um",
        "vtail_v", "n1_v", "n2_v", "vbias_v", "vout_v",
        "nf_m1", "nf_m2", "nf_m3", "nf_m4", "nf_m5", "nf_m6", "nf_m7",
    )
    out = []
    for name in fields:
        value = row[name]
        if name.startswith("nf_"):
            out.append(int(value))
        else:
            out.append(q(value))
    return tuple(out)


def range_summary(rows: list[Mapping[str, Any]], fields: Iterable[str]) -> dict[str, Any]:
    result = {}
    for name in fields:
        values = [f(row[name]) for row in rows]
        result[name] = {
            "minimum": min(values),
            "maximum": max(values),
            "unique_count": len({q(value) for value in values}),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    base = Path("examples/two_stage_opamp/generated/assignment_synthesis")
    parser.add_argument("--json", type=Path, default=base / "complete_assignments.json")
    parser.add_argument("--csv", type=Path, default=base / "complete_assignments.csv")
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=Path("examples/two_stage_opamp/generated/compiled_circuit_model.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=base / "integrity_audit")
    args = parser.parse_args()

    artifact = load_json(args.json)
    csv_rows = load_csv(args.csv)
    json_rows = list(artifact["assignments"])
    model = load_json(args.compiled_model)

    rules = model["project_inputs"]["design_rules"]
    intersection = rules["technology_intersection"]
    operating = rules["operating_conditions"]
    all_mos = rules["device_constraints"]["all_mos"]

    current_rtol = f(intersection["current_relative_tolerance"])
    current_atol = f(intersection["current_absolute_tolerance_a"])
    node_tol = f(intersection["node_voltage_tolerance_v"])
    width_rtol = f(intersection["width_relation_relative_tolerance"])
    vdd = f(operating["vdd_v"])
    vss = f(operating["vss_v"])
    vin = f(operating["vin_cm_v"])
    finger_min = f(all_mos["width_min_um"])
    finger_max = f(all_mos["width_max_um"])

    failures = Counter()
    failure_rows: list[dict[str, Any]] = []

    id_counter = Counter(row["assignment_id"] for row in json_rows)
    duplicate_ids = sorted(key for key, count in id_counter.items() if count > 1)

    canonical_counter = Counter(canonical_key(row) for row in json_rows)
    provenance_duplicates = sum(count - 1 for count in canonical_counter.values() if count > 1)

    physical_counter = Counter(assignment_equivalence_key(row) for row in json_rows)
    physical_duplicates = sum(count - 1 for count in physical_counter.values() if count > 1)

    required_fields = {
        "assignment_id",
        "i_m1_a", "i_m2_a", "i_m3_a", "i_m4_a", "i_m5_a", "i_m6_a", "i_m7_a",
        "w_m1_um", "w_m2_um", "w_m3_um", "w_m4_um", "w_m5_um", "w_m6_um", "w_m7_um",
        "vtail_v", "n1_v", "n2_v", "vbias_v", "vout_v",
        "nf_m1", "nf_m2", "nf_m3", "nf_m4", "nf_m5", "nf_m6", "nf_m7",
        "w_finger_m1_um", "w_finger_m2_um", "w_finger_m3_um", "w_finger_m4_um",
        "w_finger_m5_um", "w_finger_m6_um", "w_finger_m7_um",
        "second_stage_ratio_left", "second_stage_ratio_right",
        "second_stage_ratio_relative_error",
        "m1_technology_row_index", "m3_technology_row_index", "m4_technology_row_index",
        "m5_technology_row_index", "m6_lower_technology_row_index",
        "m6_upper_technology_row_index", "m6_interpolation_fraction",
        "m7_technology_row_index",
    }

    for index, row in enumerate(json_rows):
        row_failures = []

        missing = sorted(required_fields - set(row))
        if missing:
            failures["missing_fields"] += 1
            row_failures.append(f"missing_fields={missing}")
            failure_rows.append({"row": index, "assignment_id": row.get("assignment_id"), "failures": row_failures})
            continue

        relations = [
            ("i_m1_half_i_m5", f(row["i_m1_a"]), 0.5 * f(row["i_m5_a"]), current_rtol, current_atol),
            ("i_m2_half_i_m5", f(row["i_m2_a"]), 0.5 * f(row["i_m5_a"]), current_rtol, current_atol),
            ("i_m3_eq_i_m1", f(row["i_m3_a"]), f(row["i_m1_a"]), current_rtol, current_atol),
            ("i_m4_eq_i_m2", f(row["i_m4_a"]), f(row["i_m2_a"]), current_rtol, current_atol),
            ("i_m6_eq_i_m7", f(row["i_m6_a"]), f(row["i_m7_a"]), current_rtol, current_atol),
        ]
        for name, actual, target, rtol, atol in relations:
            if not close(actual, target, rtol=rtol, atol=atol):
                failures[name] += 1
                row_failures.append(name)

        exact_relations = [
            ("w_m2_eq_w_m1", f(row["w_m2_um"]), f(row["w_m1_um"])),
            ("w_m4_eq_w_m3", f(row["w_m4_um"]), f(row["w_m3_um"])),
        ]
        for name, actual, target in exact_relations:
            if not close(actual, target, rtol=1e-12, atol=1e-12):
                failures[name] += 1
                row_failures.append(name)

        left = f(row["w_m6_um"]) / f(row["w_m4_um"])
        right = 2.0 * f(row["w_m7_um"]) / f(row["w_m5_um"])
        if not close(left, right, rtol=width_rtol, atol=0.0):
            failures["second_stage_width_relation"] += 1
            row_failures.append("second_stage_width_relation")

        node_checks = {
            "vtail_below_vss": f(row["vtail_v"]) < vss - node_tol,
            "vtail_above_vin": f(row["vtail_v"]) > vin + node_tol,
            "n1_outside_supply": not (vss - node_tol <= f(row["n1_v"]) <= vdd + node_tol),
            "n2_outside_supply": not (vss - node_tol <= f(row["n2_v"]) <= vdd + node_tol),
            "vbias_outside_supply": not (vss - node_tol <= f(row["vbias_v"]) <= vdd + node_tol),
            "vout_outside_supply": not (vss - node_tol <= f(row["vout_v"]) <= vdd + node_tol),
        }
        for name, failed in node_checks.items():
            if failed:
                failures[name] += 1
                row_failures.append(name)

        for device in range(1, 8):
            width = f(row[f"w_m{device}_um"])
            nf = int(row[f"nf_m{device}"])
            finger = f(row[f"w_finger_m{device}_um"])
            if nf < 1:
                failures[f"nf_m{device}_invalid"] += 1
                row_failures.append(f"nf_m{device}_invalid")
            if not close(width, nf * finger, rtol=1e-12, atol=1e-9):
                failures[f"finger_reconstruction_m{device}"] += 1
                row_failures.append(f"finger_reconstruction_m{device}")
            if not (finger_min - 1e-12 <= finger <= finger_max + 1e-12):
                failures[f"finger_width_m{device}_illegal"] += 1
                row_failures.append(f"finger_width_m{device}_illegal")

        frac = f(row["m6_interpolation_fraction"])
        if not (0.0 <= frac <= 1.0):
            failures["m6_interpolation_fraction_invalid"] += 1
            row_failures.append("m6_interpolation_fraction_invalid")

        for field in (
            "m1_technology_row_index",
            "m3_technology_row_index",
            "m4_technology_row_index",
            "m5_technology_row_index",
            "m6_lower_technology_row_index",
            "m6_upper_technology_row_index",
            "m7_technology_row_index",
        ):
            if int(row[field]) < 0:
                failures[f"{field}_invalid"] += 1
                row_failures.append(f"{field}_invalid")

        if row_failures and len(failure_rows) < 1000:
            failure_rows.append(
                {
                    "row": index,
                    "assignment_id": row["assignment_id"],
                    "failures": row_failures,
                }
            )

    csv_json_count_match = len(csv_rows) == len(json_rows)
    csv_json_ids_match = [row["assignment_id"] for row in csv_rows] == [
        row["assignment_id"] for row in json_rows
    ]

    independent_fields = ("i_m5_a", "w_m1_um", "vout_v")
    coverage = range_summary(json_rows, independent_fields)

    bucket_counts = {
        "i_m5_a": Counter(q(row["i_m5_a"]) for row in json_rows),
        "vout_v": Counter(q(row["vout_v"]) for row in json_rows),
        "nf_m1": Counter(int(row["nf_m1"]) for row in json_rows),
        "nf_m6": Counter(int(row["nf_m6"]) for row in json_rows),
        "nf_m7": Counter(int(row["nf_m7"]) for row in json_rows),
    }

    cap_reached = bool(
        artifact.get("input_rejection_counts", {}).get("candidate_cap_reached", 0)
    )
    exhaustive = not cap_reached

    checks = {
        "artifact_status_pass": artifact.get("status") == "PASS",
        "json_assignment_count_matches_metadata": len(json_rows) == artifact.get("complete_assignment_count"),
        "csv_row_count_matches_json": csv_json_count_match,
        "csv_assignment_ids_match_json": csv_json_ids_match,
        "assignment_ids_unique": not duplicate_ids,
        "canonical_rows_unique": provenance_duplicates == 0,
        "physical_assignments_unique": physical_duplicates == 0,
        "all_required_constraints_pass": not failures,
        "all_rows_have_required_fields": all(required_fields <= set(row) for row in json_rows),
        "input_candidate_cap_not_reached": not cap_reached,
    }

    audit_status = (
        "PASS"
        if all(value for key, value in checks.items() if key != "input_candidate_cap_not_reached")
        else "FAIL"
    )
    coverage_status = "EXHAUSTIVE" if exhaustive else "TRUNCATED_BY_INPUT_CANDIDATE_CAP"

    report = {
        "artifact": "openams.assignment_integrity_audit",
        "schema_version": 1,
        "status": audit_status,
        "coverage_status": coverage_status,
        "source_files": {
            "complete_assignments_json": {
                "path": str(args.json.resolve()),
                "sha256": sha256(args.json),
            },
            "complete_assignments_csv": {
                "path": str(args.csv.resolve()),
                "sha256": sha256(args.csv),
            },
            "compiled_model": {
                "path": str(args.compiled_model.resolve()),
                "sha256": sha256(args.compiled_model),
            },
        },
        "counts": {
            "metadata_assignment_count": artifact.get("complete_assignment_count"),
            "json_assignment_count": len(json_rows),
            "csv_assignment_count": len(csv_rows),
            "unique_assignment_ids": len(id_counter),
            "unique_canonical_rows": len(canonical_counter),
            "unique_physical_assignments": len(physical_counter),
            "duplicate_assignment_ids": len(duplicate_ids),
            "canonical_duplicate_rows": provenance_duplicates,
            "physical_duplicate_rows": physical_duplicates,
            "constraint_failure_rows": sum(failures.values()),
        },
        "checks": checks,
        "constraint_failure_counts": dict(failures),
        "coverage": coverage,
        "bucket_counts": {
            name: {str(key): value for key, value in sorted(counter.items(), key=lambda item: item[0])}
            for name, counter in bucket_counts.items()
        },
        "cap_analysis": {
            "configured_max_assignments": intersection.get("max_assignments"),
            "input_candidate_count": artifact.get("input_bias_candidate_count"),
            "input_candidate_cap_reached": cap_reached,
            "exhaustive_coverage_proven": exhaustive,
            "interpretation": (
                "Assignments may all be valid and unique, but exhaustive coverage "
                "is not proven because input candidate construction hit its cap."
                if cap_reached
                else "Input candidate construction did not hit its configured cap."
            ),
        },
        "sample_failures": failure_rows,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "assignment_integrity_audit.json"
    md_path = args.output_dir / "ASSIGNMENT_INTEGRITY_AUDIT.md"
    duplicate_path = args.output_dir / "duplicate_summary.csv"

    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    with duplicate_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["duplicate_type", "duplicate_row_count"])
        writer.writerow(["assignment_id", sum(count - 1 for count in id_counter.values() if count > 1)])
        writer.writerow(["canonical_with_provenance", provenance_duplicates])
        writer.writerow(["physical_ignoring_provenance", physical_duplicates])

    md = f"""# OpenAMS Assignment Integrity Audit

## Verdict

- **Integrity:** {audit_status}
- **Coverage:** {coverage_status}
- **Assignments:** {len(json_rows)}
- **Unique physical assignments:** {len(physical_counter)}
- **Physical duplicates:** {physical_duplicates}
- **Constraint failures:** {sum(failures.values())}

## Meaning

`PASS` means the retained rows are internally consistent with the currently
encoded equations, width/finger rules, voltage bounds, and provenance contract.

`TRUNCATED_BY_INPUT_CANDIDATE_CAP` means the audit does not prove that the
78,959 assignments exhaust the complete physical DC region.

## Checks

```json
{json.dumps(checks, indent=2)}
```

## Independent-Space Coverage

```json
{json.dumps(coverage, indent=2)}
```

## Cap Analysis

```json
{json.dumps(report["cap_analysis"], indent=2)}
```

## Constraint Failures

```json
{json.dumps(dict(failures), indent=2)}
```
"""
    md_path.write_text(md, encoding="utf-8")

    print("===== OPENAMS COMPLETE-ASSIGNMENT INTEGRITY AUDIT =====")
    print(f"integrity:         {audit_status}")
    print(f"coverage:          {coverage_status}")
    print(f"json assignments:  {len(json_rows)}")
    print(f"csv assignments:   {len(csv_rows)}")
    print(f"unique IDs:        {len(id_counter)}")
    print(f"unique physical:   {len(physical_counter)}")
    print(f"physical duplicates:{physical_duplicates}")
    print(f"constraint failures:{sum(failures.values())}")
    print(f"cap reached:       {cap_reached}")
    print(f"json report:       {json_path}")
    print(f"markdown report:   {md_path}")

    return 0 if audit_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

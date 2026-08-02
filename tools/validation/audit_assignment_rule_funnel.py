#!/usr/bin/env python3
"""Rule-by-rule funnel audit for OpenAMS Step 5."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from openams.synthesis.complete_assignments import (
    _build_input_candidates,
    _construct_complete,
    _technology_path,
    load_rows,
)


def add(stages, rule_id, description, before, after, notes=""):
    rejected = before - after
    stages.append({
        "rule_id": rule_id,
        "description": description,
        "before": before,
        "rejected": rejected,
        "retained": after,
        "retained_percent": (100.0 * after / before) if before else 0.0,
        "notes": notes,
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    base = Path("examples/two_stage_opamp/generated/assignment_synthesis")
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=Path("examples/two_stage_opamp/generated/compiled_circuit_model.json"),
    )
    parser.add_argument(
        "--independent-regions",
        type=Path,
        default=base / "independent_regions.json",
    )
    parser.add_argument(
        "--complete-assignments",
        type=Path,
        default=base / "complete_assignments.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=base / "rule_funnel_audit",
    )
    args = parser.parse_args()

    model = json.loads(args.compiled_model.read_text(encoding="utf-8"))
    independent = json.loads(args.independent_regions.read_text(encoding="utf-8"))
    complete = json.loads(args.complete_assignments.read_text(encoding="utf-8"))
    rows = load_rows(_technology_path(model))

    stages = []

    # The production code currently exposes aggregate rejection counts rather
    # than stage snapshots. This audit converts those counts into an explicit
    # first-pass funnel and clearly marks where counts are comparison counts
    # rather than unique-candidate counts.
    input_before = int(complete["input_bias_candidate_count"])
    input_rejections = dict(complete.get("input_rejection_counts", {}))
    join_rejections = dict(complete.get("join_rejection_counts", {}))
    final_count = int(complete["complete_assignment_count"])

    add(
        stages,
        "F00",
        "Correlated input-bias candidates retained by Step 5",
        input_before,
        input_before,
        "This count already reflects all input-stage rules and deduplication.",
    )

    running = input_before
    for key, description in [
        ("m1_width_illegal", "Reject illegal M1 total width/NF realization"),
        ("vtail_out_of_bounds", "Reject Vtail outside topology bounds"),
        ("m5_voltage_mismatch", "Reject M5 drain-voltage mismatch"),
        ("m5_width_illegal", "Reject illegal M5 total width/NF realization"),
        ("m3_n1_mismatch", "Reject M3 diode/N1 mismatch"),
        ("m3_width_illegal", "Reject illegal M3 total width/NF realization"),
        ("m4_current_mismatch", "Reject M4 current mismatch"),
    ]:
        count = int(input_rejections.get(key, 0))
        stages.append({
            "rule_id": key,
            "description": description,
            "before": None,
            "rejected": count,
            "retained": None,
            "retained_percent": None,
            "notes": (
                "Comparison failure count from nested technology-row loops; "
                "not a unique-candidate funnel count."
            ),
        })

    for key, description in [
        ("m7_vbias_mismatch", "Reject M7 VGS inconsistent with Vbias"),
        ("m7_vout_outside_domain", "Reject Vout outside intent/specification domain"),
        ("m6_vds_grid_missing", "Reject missing M6 support at required VSD"),
        ("m6_density_not_bracketed", "Reject unbracketed M6 density interpolation"),
        ("m6_n2_mismatch", "Reject interpolated M6 VSG inconsistent with N2"),
        ("empty_common_current_interval", "Reject empty common I6=I7 width interval"),
        ("illegal_output_width", "Reject illegal M6/M7 width or NF"),
    ]:
        count = int(join_rejections.get(key, 0))
        stages.append({
            "rule_id": key,
            "description": description,
            "before": None,
            "rejected": count,
            "retained": None,
            "retained_percent": None,
            "notes": (
                "Comparison failure count from indexed output-stage search; "
                "not a unique-candidate funnel count."
            ),
        })

    add(
        stages,
        "F99",
        "Complete assignments retained after all encoded rules",
        input_before,
        final_count,
        (
            "This direct before/after comparison is informative but not a true "
            "sequential funnel because output-stage expansion occurs between them."
        ),
    )

    report = {
        "artifact": "openams.assignment_rule_funnel_audit",
        "schema_version": 1,
        "status": "PARTIAL",
        "reason": (
            "Current Step 5 stores final assignments and aggregate nested-loop "
            "rejection totals, but not per-rule unique candidate snapshots."
        ),
        "counts": {
            "input_bias_candidates": input_before,
            "complete_assignments": final_count,
            "candidate_cap_reached": bool(
                input_rejections.get("candidate_cap_reached", 0)
            ),
        },
        "stages": stages,
        "required_production_fix": {
            "description": (
                "Instrument complete_assignments.py so each rule receives and "
                "returns a materialized or streaming candidate set with before, "
                "rejected, retained, and unique-key counts."
            ),
            "required_stages": [
                "M1 width/NF",
                "Vtail bounds",
                "N1 bounds",
                "M5 VDS agreement",
                "M5 width/NF",
                "M3 diode and N1 agreement",
                "M3 width/NF",
                "M4 VGS/current/N2",
                "input deduplication",
                "candidate cap",
                "M7 Vbias",
                "Vout window",
                "M6 VSD support",
                "M6 density interpolation",
                "M6 N2 agreement",
                "common output-current interval",
                "M6/M7 legal widths",
                "final physical deduplication",
            ],
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "assignment_rule_funnel_audit.json"
    csv_path = args.output_dir / "assignment_rule_funnel_audit.csv"
    md_path = args.output_dir / "ASSIGNMENT_RULE_FUNNEL_AUDIT.md"

    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "rule_id", "description", "before", "rejected",
                "retained", "retained_percent", "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(stages)

    lines = [
        "# OpenAMS Assignment Rule Funnel Audit",
        "",
        "## Verdict",
        "",
        "- **Status:** PARTIAL",
        f"- **Input-bias candidates:** {input_before}",
        f"- **Complete assignments:** {final_count}",
        f"- **Candidate cap reached:** {report['counts']['candidate_cap_reached']}",
        "",
        "The current rejection counters are not a valid sequential funnel. They "
        "count failed comparisons inside nested loops, so one partial candidate "
        "may be counted as rejected many times against different technology rows.",
        "",
        "## Available counts",
        "",
        "| Rule | Description | Rejected comparisons |",
        "|---|---|---:|",
    ]
    for stage in stages:
        if stage["before"] is None:
            lines.append(
                f"| {stage['rule_id']} | {stage['description']} | "
                f"{stage['rejected']} |"
            )

    lines.extend([
        "",
        "## Required correction",
        "",
        "Step 5 must be instrumented to record unique candidate sets immediately "
        "before and after every rule. Only then can we produce the trustworthy "
        "monotonic/expansion-aware funnel requested.",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("===== OPENAMS ASSIGNMENT RULE FUNNEL AUDIT =====")
    print("status: PARTIAL")
    print(f"input-bias candidates: {input_before}")
    print(f"complete assignments:  {final_count}")
    print("The current counters are nested-loop comparison failures,")
    print("not a valid rule-by-rule unique-candidate funnel.")
    print(f"json: {json_path}")
    print(f"csv:  {csv_path}")
    print(f"md:   {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

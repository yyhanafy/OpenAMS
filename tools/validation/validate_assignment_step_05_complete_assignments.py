#!/usr/bin/env python3
"""Validate legacy or topology-generic Step 5 complete assignments."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _parse_name_int(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        name, separator, count = value.partition("=")
        if not separator:
            raise SystemExit(f"invalid --continuous-samples value {value!r}; use NAME=COUNT")
        result[name] = int(count)
    return result


def _parse_name_range(values: list[str]) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    for value in values:
        name, separator, bounds = value.partition("=")
        minimum, colon, maximum = bounds.partition(":")
        if not separator or not colon:
            raise SystemExit(f"invalid --range value {value!r}; use NAME=MIN:MAX")
        result[name] = (float(minimum), float(maximum))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiled-model", type=Path, required=True)
    parser.add_argument("--independent-regions", type=Path, required=True)
    parser.add_argument("--dependent-regions", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--mode", choices=("generic", "legacy"), default="generic")
    parser.add_argument("--continuous-samples", action="append", default=[])
    parser.add_argument("--range", dest="ranges", action="append", default=[])
    parser.add_argument("--provider", choices=("inverse", "table", "plugin"), default="inverse")
    parser.add_argument("--provider-plugin")
    parser.add_argument("--technology-csv", type=Path)
    parser.add_argument("--mlp-fallback", action="store_true")
    parser.add_argument("--adaptive-cache", type=Path)
    parser.add_argument("--mlp-vgs-count", type=int, default=8)
    parser.add_argument("--mlp-vds-count", type=int, default=10)
    parser.add_argument("--max-device-candidates", type=int, default=64)
    parser.add_argument("--max-group-choices", type=int, default=64)
    parser.add_argument("--max-solutions-per-point", type=int, default=64)
    parser.add_argument("--max-assignments", type=int)
    args = parser.parse_args()

    if args.mode == "legacy":
        from openams.synthesis.complete_assignments import write_complete_assignments
        artifact = write_complete_assignments(
            args.compiled_model,
            args.independent_regions,
            args.dependent_regions,
            args.output_json,
            args.output_csv,
        )
    else:
        from openams.synthesis.generic_complete_step5 import write_generic_complete_assignments
        artifact = write_generic_complete_assignments(
            args.compiled_model,
            args.independent_regions,
            args.dependent_regions,
            args.output_json,
            args.output_csv,
            continuous_samples=_parse_name_int(args.continuous_samples),
            range_overrides=_parse_name_range(args.ranges),
            provider_kind=args.provider,
            provider_plugin=args.provider_plugin,
            technology_csv_path=args.technology_csv,
            enable_mlp_fallback=args.mlp_fallback,
            adaptive_cache_path=args.adaptive_cache,
            mlp_vgs_count=args.mlp_vgs_count,
            mlp_vds_count=args.mlp_vds_count,
            max_device_candidates=args.max_device_candidates,
            max_group_choices=args.max_group_choices,
            max_solutions_per_independent_point=args.max_solutions_per_point,
            max_assignments=args.max_assignments,
        )

    assignments = artifact.get("assignments", [])
    checks = {
        "status_pass": artifact.get("status") == "PASS",
        "complete_assignments_exist": len(assignments) > 0,
        "assignment_count_matches": artifact.get("complete_assignment_count") == len(assignments),
        "route_correct": artifact.get("recommended_route") in {
            "direct_simulation",
            "ngspice_dc_confirmation",
            "select_vout_within_feasible_window",
        },
    }
    if args.mode == "generic":
        checks.update(
            {
                "independent_grid_nonempty": artifact.get("independent_combination_count", 0) > 0,
                "provider_recorded": bool(artifact.get("device_provider")),
                "all_assignments_model_valid": all(
                    row.get("assignment_semantics") in {
                        "model_valid_dc_operating_point",
                        "model_valid_dc_operating_region",
                    }
                    for row in assignments
                ),
                "ranged_assignments_have_vout_window": all(
                    row.get("assignment_semantics")
                    != "model_valid_dc_operating_region"
                    or (
                        isinstance(row.get("vout_min_v"), (int, float))
                        and isinstance(row.get("vout_max_v"), (int, float))
                        and row["vout_min_v"] < row["vout_max_v"]
                    )
                    for row in assignments
                ),
            }
        )
    passed = all(checks.values())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        "# Assignment Synthesis Step 5 Report\n\n"
        f"**Status:** {'PASS' if passed else 'FAIL'}\n\n"
        f"- Mode: `{args.mode}`\n"
        f"- Algorithm: `{artifact.get('algorithm')}`\n"
        f"- Independent combinations: {artifact.get('independent_combination_count', 'legacy')}\n"
        f"- Complete assignments: {artifact.get('complete_assignment_count', 0)}\n"
        f"- Route: `{artifact.get('recommended_route')}`\n\n"
        "## Checks\n\n```json\n"
        + json.dumps(checks, indent=2)
        + "\n```\n\n## Rejections\n\n```json\n"
        + json.dumps(artifact.get("rejection_counts", {}), indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print("===== OPENAMS ASSIGNMENT STEP 5: COMPLETE DC ASSIGNMENTS =====")
    print(f"status:                    {'PASS' if passed else 'FAIL'}")
    print(f"mode:                      {args.mode}")
    print(f"algorithm:                 {artifact.get('algorithm')}")
    print(f"independent combinations:  {artifact.get('independent_combination_count', 'legacy')}")
    print(f"assignments:               {artifact.get('complete_assignment_count', 0)}")
    print(f"route:                     {artifact.get('recommended_route')}")
    print(f"json:                      {args.output_json}")
    print(f"csv:                       {args.output_csv}")
    if not passed:
        for name, value in checks.items():
            if not value:
                print(f"[FAIL] {name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

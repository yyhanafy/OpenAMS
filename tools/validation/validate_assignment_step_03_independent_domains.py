#!/usr/bin/env python3
"""Production validation for assignment-synthesis Step 3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openams.synthesis.independent_domains import write_independent_domains


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compiled-model",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/compiled_circuit_model.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/assignment_synthesis/"
            "independent_regions.json"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "examples/two_stage_opamp/generated/assignment_synthesis/"
            "STEP3_INDEPENDENT_REGIONS_REPORT.md"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = write_independent_domains(args.compiled_model, args.output)
    domains = artifact["domains"]
    expected = {"i_m5_a", "w_m1_um", "vout_v"}

    width = domains["w_m1_um"]
    vout = domains["vout_v"]

    checks = {
        "status_pass": artifact["status"] == "PASS",
        "declared_variables_present": set(domains) == expected,
        "current_domain_nonempty": domains["i_m5_a"]["candidate_count"] > 0,
        "width_domain_valid": (
            width["technology_minimum"] <= width["technology_maximum"]
        ),
        "width_nf_realizable": (
            width["kind"] != "total_width"
            or bool(width.get("realizable_nf_intervals"))
        ),
        "vout_continuous_interval": (
            vout["domain_type"]
            == "technology_supported_continuous_interval"
        ),
        "vout_interval_nonempty": (
            vout["technology_minimum"] <= vout["technology_maximum"]
        ),
        "next_stage_correct": artifact["next_stage"] == "derive_dependent_regions",
    }
    passed = all(checks.values())

    compact = {}
    for name, domain in domains.items():
        compact[name] = {
            "kind": domain["kind"],
            "domain_type": domain["domain_type"],
            "design_intent_minimum": domain["declared_effective_minimum"],
            "design_intent_maximum": domain["declared_effective_maximum"],
            "technology_minimum": domain.get("technology_minimum"),
            "technology_maximum": domain.get("technology_maximum"),
            "candidate_count": domain["candidate_count"],
            "supporting_row_count": domain.get("supporting_row_count"),
            "nf_min": domain.get("nf_min"),
            "nf_max": domain.get("nf_max"),
            "finger_width_min_um": domain.get("finger_width_min_um"),
            "finger_width_max_um": domain.get("finger_width_max_um"),
        }

    report = f"""# Assignment Synthesis Step 3 Report

## Status

**{"PASS" if passed else "FAIL"}**

## Independent Domains

```json
{json.dumps(compact, indent=2)}
```

## Checks

```json
{json.dumps(checks, indent=2)}
```

## Meaning

- Current and terminal-voltage variables retain filtered technology support.
- Node-voltage variables are continuous technology-supported intervals.
- A `total_width` range comes from design intent and is accepted when legal
  integer-finger realizations exist within the technology finger-width limits.
- No dependent quantity is derived in Step 3.
"""
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")

    print("===== OPENAMS ASSIGNMENT STEP 3: INDEPENDENT DOMAINS =====")
    print(f"status:       {'PASS' if passed else 'FAIL'}")
    for name, domain in domains.items():
        print(
            f"{name}: kind={domain['kind']} "
            f"type={domain['domain_type']} "
            f"technology=[{domain.get('technology_minimum')}, "
            f"{domain.get('technology_maximum')}] "
            f"candidates={domain['candidate_count']}"
        )
        if domain.get("nf_min") is not None:
            print(
                f"  NF={domain['nf_min']}..{domain['nf_max']} "
                f"Wfinger={domain['finger_width_min_um']}.."
                f"{domain['finger_width_max_um']} um"
            )
    print(f"output:       {args.output}")
    print(f"report:       {args.report}")

    if not passed:
        for name, value in checks.items():
            if not value:
                print(f"[FAIL] {name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

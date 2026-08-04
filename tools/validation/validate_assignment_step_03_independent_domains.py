#!/usr/bin/env python3
"""Generic production validation for assignment-synthesis Step 3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from openams.synthesis.independent_domains import write_independent_domains


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--compiled-model",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--report",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--mode",
        choices=("generic", "two_stage_regression"),
        default="generic",
    )

    return parser.parse_args()


def load_expected_variables(
    compiled_model: Path,
) -> dict[str, Mapping[str, Any]]:
    model = json.loads(
        compiled_model.read_text(encoding="utf-8")
    )

    declared = (
        model.get("synthesis_interface", {})
        .get("independent_variables", [])
    )

    result: dict[str, Mapping[str, Any]] = {}

    for item in declared:
        variable_id = str(item.get("id", "")).strip()

        if not variable_id:
            raise SystemExit(
                "independent-variable declaration has no id"
            )

        original = item.get("original", {})

        if not isinstance(original, Mapping):
            raise SystemExit(
                f"{variable_id!r} has no mapping definition"
            )

        result[variable_id] = original

    if not result:
        raise SystemExit(
            "compiled model declares no independent variables"
        )

    return result


def domain_has_valid_support(
    domain: Mapping[str, Any],
) -> bool:
    domain_type = str(
        domain.get("domain_type", "")
    )

    minimum = domain.get("technology_minimum")
    maximum = domain.get("technology_maximum")

    bounds_valid = (
        minimum is not None
        and maximum is not None
        and float(minimum) <= float(maximum)
    )

    if not bounds_valid:
        return False

    if domain_type == "technology_supported_continuous_interval":
        return True

    if domain_type in {
        "technology_supported_total_width_interval",
        "technology_realizable_continuous_total_width",
    }:
        return bool(
            domain.get("realizable_nf_intervals")
        )

    candidate_count = int(
        domain.get("candidate_count", 0)
    )

    return candidate_count > 0


def main() -> int:
    args = parse_args()

    expected_definitions = load_expected_variables(
        args.compiled_model
    )

    artifact = write_independent_domains(
        args.compiled_model,
        args.output,
    )

    domains = artifact["domains"]

    expected_ids = set(expected_definitions)
    actual_ids = set(domains)

    per_variable_checks: dict[str, dict[str, bool]] = {}

    for variable_id, definition in expected_definitions.items():
        domain = domains.get(variable_id)

        if domain is None:
            per_variable_checks[variable_id] = {
                "domain_present": False,
                "kind_matches": False,
                "declared_bounds_valid": False,
                "technology_support_valid": False,
                "technology_provenance_present": False,
            }
            continue

        declared_minimum = domain.get(
            "declared_effective_minimum"
        )
        declared_maximum = domain.get(
            "declared_effective_maximum"
        )

        per_variable_checks[variable_id] = {
            "domain_present": True,
            "kind_matches": (
                str(domain.get("kind", "")).lower()
                == str(definition.get("kind", "")).lower()
            ),
            "declared_bounds_valid": (
                declared_minimum is not None
                and declared_maximum is not None
                and float(declared_minimum)
                <= float(declared_maximum)
            ),
            "technology_support_valid": (
                domain_has_valid_support(domain)
            ),
            "technology_provenance_present": (
                bool(
                    domain.get("technology_records")
                    or domain.get("device_domains")
                    or domain.get("realizable_nf_intervals")
                )
            ),
        }

    checks = {
        "status_pass": artifact.get("status") == "PASS",
        "declared_variables_present": actual_ids == expected_ids,
        "all_variable_checks_pass": all(
            all(item.values())
            for item in per_variable_checks.values()
        ),
        "next_stage_correct": (
            artifact.get("next_stage")
            == "derive_dependent_regions"
        ),
    }

    if args.mode == "two_stage_regression":
        expected_two_stage = {
            "i_m5_a",
            "w_m1_um",
            "vout_v",
        }

        checks["two_stage_variable_set_matches"] = (
            actual_ids == expected_two_stage
        )

        if actual_ids == expected_two_stage:
            width = domains["w_m1_um"]
            vout = domains["vout_v"]

            checks.update(
                {
                    "two_stage_current_domain_nonempty": (
                        domains["i_m5_a"]["candidate_count"] > 0
                    ),
                    "two_stage_width_nf_realizable": (
                        width["kind"] != "total_width"
                        or bool(
                            width.get("realizable_nf_intervals")
                        )
                    ),
                    "two_stage_vout_continuous": (
                        vout["domain_type"]
                        == "technology_supported_continuous_interval"
                    ),
                }
            )

    passed = all(checks.values())

    compact: dict[str, Any] = {}

    for name, domain in domains.items():
        compact[name] = {
            "kind": domain.get("kind"),
            "device": domain.get("device"),
            "domain_type": domain.get("domain_type"),
            "design_intent_minimum": domain.get(
                "declared_effective_minimum"
            ),
            "design_intent_maximum": domain.get(
                "declared_effective_maximum"
            ),
            "technology_minimum": domain.get(
                "technology_minimum"
            ),
            "technology_maximum": domain.get(
                "technology_maximum"
            ),
            "candidate_count": domain.get(
                "candidate_count"
            ),
            "supporting_row_count": domain.get(
                "supporting_row_count"
            ),
            "source_node": domain.get("source_node"),
            "source_voltage_v": domain.get(
                "source_voltage_v"
            ),
            "device_terminal": domain.get(
                "device_terminal"
            ),
            "nf_min": domain.get("nf_min"),
            "nf_max": domain.get("nf_max"),
            "finger_width_min_um": domain.get(
                "finger_width_min_um"
            ),
            "finger_width_max_um": domain.get(
                "finger_width_max_um"
            ),
        }

    report_lines = [
        "# Assignment Synthesis Step 3 Report",
        "",
        "## Status",
        "",
        f"**{'PASS' if passed else 'FAIL'}**",
        "",
        f"- **Mode:** `{args.mode}`",
        f"- **Circuit:** `{artifact.get('circuit_name')}`",
        f"- **Independent variables:** {len(domains)}",
        "",
        "## Independent Domains",
        "",
        "```json",
        json.dumps(compact, indent=2),
        "```",
        "",
        "## Per-Variable Checks",
        "",
        "```json",
        json.dumps(per_variable_checks, indent=2),
        "```",
        "",
        "## Global Checks",
        "",
        "```json",
        json.dumps(checks, indent=2),
        "```",
        "",
        "## Meaning",
        "",
        (
            "- Every independent variable declared in the compiled model "
            "must have a generated technology-backed domain."
        ),
        (
            "- Point-set domains must contain at least one candidate."
        ),
        (
            "- Continuous node-voltage domains must have a nonempty "
            "technology-supported interval."
        ),
        (
            "- Total-width domains must have at least one legal integer-"
            "finger realization."
        ),
        (
            "- Bias-voltage domains are absolute terminal-voltage domains "
            "derived from device technology data and resolved source voltage."
        ),
        (
            "- No dependent circuit quantity is derived in Step 3."
        ),
        "",
    ]

    args.report.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.report.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    print(
        "===== OPENAMS ASSIGNMENT STEP 3: "
        "INDEPENDENT DOMAINS ====="
    )
    print(
        f"status:       {'PASS' if passed else 'FAIL'}"
    )
    print(f"mode:         {args.mode}")
    print(
        f"circuit:      {artifact.get('circuit_name')}"
    )

    for name, domain in domains.items():
        print(
            f"{name}: "
            f"kind={domain.get('kind')} "
            f"device={domain.get('device')} "
            f"type={domain.get('domain_type')} "
            f"technology=["
            f"{domain.get('technology_minimum')}, "
            f"{domain.get('technology_maximum')}] "
            f"candidates={domain.get('candidate_count')}"
        )

        if domain.get("source_node") is not None:
            print(
                f"  terminal={domain.get('device_terminal')} "
                f"source={domain.get('source_node')} "
                f"Vsource={domain.get('source_voltage_v')} V"
            )

        if domain.get("nf_min") is not None:
            print(
                f"  NF={domain.get('nf_min')}.."
                f"{domain.get('nf_max')} "
                f"Wfinger={domain.get('finger_width_min_um')}.."
                f"{domain.get('finger_width_max_um')} um"
            )

    print(f"output:       {args.output}")
    print(f"report:       {args.report}")

    if not passed:
        for name, value in checks.items():
            if not value:
                print(f"[FAIL] {name}")

        for variable, variable_checks in per_variable_checks.items():
            for name, value in variable_checks.items():
                if not value:
                    print(
                        f"[FAIL] {variable}: {name}"
                    )

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

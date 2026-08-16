#!/usr/bin/env python3
"""Gate 4A validator: classify design-intent declarations by subsystem."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--design-intent",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs/design_intent.yaml"),
    )
    parser.add_argument(
        "--design-rules",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs/design_rules.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/validation/evidence/gate_04_constraints"),
    )
    return parser.parse_args()


def canonical_current_name(name: str) -> str:
    token = name.strip().lower()
    if not token.startswith("i_m"):
        raise ValueError(f"unsupported current variable {name!r}")
    device = token[2:].upper()
    return f"device.{device}.current"


def translate_linear_equation(equation: str) -> str:
    """Translate the current-relation notation into compiler canonical syntax."""

    expression = equation.replace("=", "==", 1)
    parts = expression.split()

    translated: list[str] = []
    for part in parts:
        stripped = part.strip()
        prefix = ""
        suffix = ""

        while stripped and stripped[0] in "(+-":
            prefix += stripped[0]
            stripped = stripped[1:]
        while stripped and stripped[-1] in "),":
            suffix = stripped[-1] + suffix
            stripped = stripped[:-1]

        if stripped.lower().startswith("i_m"):
            stripped = canonical_current_name(stripped)

        translated.append(prefix + stripped + suffix)

    return " ".join(translated)



def validate_dc_propagation(dc_propagation: dict[str, Any]) -> list[str]:
    """Validate designer-authored ordered DC-propagation metadata."""
    errors: list[str] = []

    if not dc_propagation:
        return errors

    if dc_propagation.get("schema_version") != 1:
        errors.append("dc_propagation.schema_version must equal 1")

    if dc_propagation.get("execution") != "ordered":
        errors.append("dc_propagation.execution must equal 'ordered'")

    operations = dc_propagation.get("operations")
    if not isinstance(operations, list):
        errors.append("dc_propagation.operations must be a list")
        return errors

    allowed_types = {
        "equation",
        "technology_lookup",
        "lower_bound",
        "upper_bound",
        "interval_alias",
    }

    seen_ids: set[str] = set()

    for index, operation in enumerate(operations):
        location = f"dc_propagation.operations[{index}]"

        if not isinstance(operation, dict):
            errors.append(f"{location} must be a mapping")
            continue

        operation_id = operation.get("id")
        operation_type = operation.get("type")
        target = operation.get("target")

        if not isinstance(operation_id, str) or not operation_id.strip():
            errors.append(f"{location}.id must be a nonempty string")
        elif operation_id in seen_ids:
            errors.append(
                f"{location}.id duplicates operation '{operation_id}'"
            )
        else:
            seen_ids.add(operation_id)

        if operation_type not in allowed_types:
            errors.append(
                f"{location}.type must be one of "
                f"{sorted(allowed_types)}"
            )

        if not isinstance(target, str) or not target.strip():
            errors.append(f"{location}.target must be a nonempty string")

        if operation_type in {
            "equation",
            "lower_bound",
            "upper_bound",
        }:
            expression = operation.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                errors.append(
                    f"{location}.expression must be a nonempty string"
                )

    return errors


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    intent = yaml.safe_load(args.design_intent.read_text(encoding="utf-8"))
    rules = yaml.safe_load(args.design_rules.read_text(encoding="utf-8"))

    circuit_intent = intent.get("circuit_intent", {})
    parameterization = intent.get("synthesis_parameterization", {})
    assignment_synthesis = intent.get("assignment_synthesis", {})
    dc_propagation = circuit_intent.get("dc_propagation", {}) or {}

    dc_propagation_errors = validate_dc_propagation(dc_propagation)
    if dc_propagation_errors:
        print("===== OPENAMS GATE 4A: CONSTRAINT CLASSIFICATION =====")
        print("status:              FAIL")
        for error in dc_propagation_errors:
            print(f"dc_propagation:      {error}")
        return 1

    classified: list[dict[str, Any]] = []
    compiler_constraints: list[dict[str, Any]] = []

    for item in circuit_intent.get("current_relations", []) or []:
        identifier = str(item["id"])
        equation = str(item["equation"])
        translated = translate_linear_equation(equation)
        category = "linear_compiler_constraint"
        kind = "topology_derived" if identifier == "output_node_kcl" else "equality"

        record = {
            "id": identifier,
            "source_path": "circuit_intent.current_relations",
            "original": equation,
            "category": category,
            "owner": "synthesis.constraint_compiler",
            "reason": "linear equality or KCL-compatible relation",
            "canonical_expression": translated,
            "compiler_kind": kind,
        }
        classified.append(record)
        compiler_constraints.append(
            {
                "name": identifier,
                "kind": kind,
                "expression": translated,
                "source": "design_intent",
            }
        )

    for item in circuit_intent.get("size_relations", []) or []:
        identifier = str(item["id"])
        equation = str(item["equation"])
        classified.append(
            {
                "id": identifier,
                "source_path": "circuit_intent.size_relations",
                "original": equation,
                "fixed_length_equivalent": item.get("fixed_length_equivalent"),
                "category": "topology_heuristic",
                "owner": "topology_specific_synthesis_adapter",
                "reason": "contains ratios/products and is intentionally outside the linear compiler",
                "canonical_expression": None,
                "compiler_kind": None,
            }
        )

    for name, definition in (
        parameterization.get("independent_variables", {}) or {}
    ).items():
        classified.append(
            {
                "id": str(name),
                "source_path": "synthesis_parameterization.independent_variables",
                "original": definition,
                "category": "synthesis_parameter",
                "owner": "synthesis_parameterization",
                "reason": "declares scan dimensions rather than an executable equality",
                "canonical_expression": None,
                "compiler_kind": None,
            }
        )

    for name in parameterization.get("dependent_quantities", []) or []:
        classified.append(
            {
                "id": str(name),
                "source_path": "synthesis_parameterization.dependent_quantities",
                "original": str(name),
                "category": "dependent_quantity_declaration",
                "owner": "synthesis_adapter_or_emitter",
                "reason": "declares expected derived outputs rather than a join predicate",
                "canonical_expression": None,
                "compiler_kind": None,
            }
        )

    for group in assignment_synthesis.get("groups", []) or []:
        classified.append(
            {
                "id": str(group["id"]),
                "source_path": "assignment_synthesis.groups",
                "original": group,
                "category": "dependency_group",
                "owner": "hierarchical_synthesis_workflow",
                "reason": "declares stage ordering, devices, variables, solver, and constraint references",
                "canonical_expression": None,
                "compiler_kind": None,
            }
        )

    for key in (
        "operating_conditions",
        "device_constraints",
        "technology_intersection",
        "assignment_rules",
        "simulation_constraints",
    ):
        classified.append(
            {
                "id": key,
                "source_path": f"design_rules.{key}",
                "original": rules.get(key),
                "category": (
                    "technology_region_constraint"
                    if key in {"device_constraints", "technology_intersection"}
                    else "simulation_constraint"
                    if key == "simulation_constraints"
                    else "operating_or_assignment_policy"
                ),
                "owner": (
                    "technology"
                    if key in {"device_constraints", "technology_intersection"}
                    else "simulation"
                    if key == "simulation_constraints"
                    else "orchestration"
                ),
                "reason": "not a canonical linear equality",
                "canonical_expression": None,
                "compiler_kind": None,
            }
        )

    for operation in dc_propagation.get("operations", []) or []:
        classified.append(
            {
                "id": str(operation["id"]),
                "source_path": "dc_propagation.operations",
                "original": operation,
                "category": "dc_propagation_operation",
                "owner": "assignment_synthesis.dc_propagation",
                "reason": (
                    "designer-authored ordered DC propagation operation; "
                    "preserved for review and later Step-5 execution"
                ),
                "canonical_expression": operation.get("expression"),
                "compiler_kind": None,
            }
        )

    categories: dict[str, int] = {}
    for item in classified:
        categories[item["category"]] = categories.get(item["category"], 0) + 1

    summary = {
        "gate": "4A",
        "proof": "Design-intent declarations classified by owning subsystem",
        "status": "PASS",
        "design_intent": str(args.design_intent),
        "design_rules": str(args.design_rules),
        "classification_count": len(classified),
        "category_counts": dict(sorted(categories.items())),
        "compiler_constraint_count": len(compiler_constraints),
        "dc_propagation_operation_count": len(
            dc_propagation.get("operations", []) or []
        ),
        "dc_propagation": dc_propagation,
        "unsupported_for_linear_compiler": [
            item["id"]
            for item in classified
            if item["category"] == "topology_heuristic"
        ],
        "compiler_constraints": compiler_constraints,
        "classified_items": classified,
    }

    (args.output_dir / "constraint_classification.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "compiler_constraints.json").write_text(
        json.dumps(compiler_constraints, indent=2) + "\n",
        encoding="utf-8",
    )

    report_lines = [
        "# Gate 4A Constraint Classification Report",
        "",
        "## Summary",
        "",
        "- **Status:** PASS",
        f"- **Classified items:** {len(classified)}",
        f"- **Linear compiler constraints:** {len(compiler_constraints)}",
        "- **Topology heuristics excluded from compiler:** "
        + (
            ", ".join(summary["unsupported_for_linear_compiler"])
            if summary["unsupported_for_linear_compiler"]
            else "None"
        ),
        "",
        "## Classification",
        "",
        "| ID | Category | Owner | Compiler expression |",
        "|---|---|---|---|",
    ]
    for item in classified:
        expression = item["canonical_expression"] or "—"
        report_lines.append(
            f"| `{item['id']}` | `{item['category']}` | "
            f"`{item['owner']}` | `{expression}` |"
        )

    report_lines.extend(
        [
            "",
            "## Compiler Scope",
            "",
            "The generic compiler receives only linear equalities, scaled equalities, "
            "and linear sums. Independent-variable declarations, dependency groups, "
            "technology filtering, simulation rules, and nonlinear topology-specific "
            "relations remain owned by their corresponding subsystems.",
            "",
            "## Gate 4A Conclusion",
            "",
            "The two-stage design intent has been decomposed into explicit subsystem "
            "responsibilities. Gate 4B may now compile only the generated "
            "`compiler_constraints.json` records against canonical region bindings.",
            "",
        ]
    )

    (args.output_dir / "CONSTRAINT_CLASSIFICATION_REPORT.md").write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    (raw_dir / "design_intent.yaml").write_text(
        args.design_intent.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (raw_dir / "design_rules.yaml").write_text(
        args.design_rules.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    print("===== OPENAMS GATE 4A: CONSTRAINT CLASSIFICATION =====")
    print("status:              PASS")
    print(f"classified_items:    {len(classified)}")
    print(f"compiler_constraints:{len(compiler_constraints)}")
    print(
        "topology_heuristics: "
        + (
            ", ".join(summary["unsupported_for_linear_compiler"])
            if summary["unsupported_for_linear_compiler"]
            else "none"
        )
    )
    print(f"evidence:            {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

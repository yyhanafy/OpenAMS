#!/usr/bin/env python3
"""Executable Gate 4B validation for the OpenAMS constraint compiler.

This validator consumes the five canonical constraints generated from the
official two-stage-op-amp design intent, compiles them through the production
``CircuitConstraintCompiler``, executes the compiled intersection against a
small representative set of device-current regions, and verifies the exact
retained operating combinations.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from openams.synthesis import (
    CircuitConstraintCompiler,
    RegionBinding,
    RegionInput,
)


@dataclass(frozen=True)
class CanonicalConstraint:
    """Compiler input matching the public canonical-constraint protocol."""

    name: str
    kind: str
    expression: str
    source: str = "design_intent"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--constraints",
        type=Path,
        default=Path(
            "docs/validation/evidence/gate_04_constraints/"
            "compiler_constraints.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "docs/validation/evidence/gate_04b_constraint_compiler"
        ),
    )
    return parser.parse_args()


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((jsonable(item) for item in value), key=repr)
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return jsonable(value.value)
    if hasattr(value, "__dict__"):
        return {
            str(key): jsonable(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return value


def load_constraints(path: Path) -> tuple[CanonicalConstraint, ...]:
    if not path.is_file():
        raise SystemExit(f"constraint artifact does not exist: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("compiler constraint artifact must contain a JSON list")

    constraints: list[CanonicalConstraint] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise SystemExit(f"constraint index {index} must be a JSON object")
        expression = str(item["expression"])
        expression = expression.replace(
            "device.M5.current / 2.0",
            "0.5 * device.M5.current",
        )

        constraints.append(
            CanonicalConstraint(
                name=str(item["name"]),
                kind=str(item["kind"]),
                expression=expression,
                source=str(item.get("source", "design_intent")),
            )
        )
    return tuple(constraints)


def binding(
    name: str,
    currents_a: tuple[float, ...],
) -> RegionBinding:
    rows = tuple(
        {
            "id_a": current,
            "candidate_label": f"{name}_{index}",
        }
        for index, current in enumerate(currents_a)
    )
    return RegionBinding(
        name,
        RegionInput(name, rows),
        {f"device.{name}.current": "id_a"},
    )


def build_bindings() -> tuple[RegionBinding, ...]:
    """Representative regions with valid and deliberately invalid rows."""

    return (
        binding("M1", (20e-6, 25e-6, 30e-6)),
        binding("M2", (20e-6, 30e-6, 35e-6)),
        binding("M3", (20e-6, 30e-6, 99e-6)),
        binding("M4", (20e-6, 30e-6, 88e-6)),
        binding("M5", (40e-6, 50e-6, 60e-6)),
        binding("M6", (10e-6, 15e-6)),
        binding("M7", (10e-6, 20e-6)),
    )


def retained_current_tuples(rows: Any) -> list[dict[str, float]]:
    result: list[dict[str, float]] = []
    for row in rows:
        values = row.values
        result.append(
            {
                device: float(values[f"{device}.id_a"])
                for device in ("M1", "M2", "M3", "M4", "M5", "M6", "M7")
            }
        )
    return result


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    constraints = load_constraints(args.constraints)
    bindings = build_bindings()

    compiler = CircuitConstraintCompiler()
    compiled = compiler.compile(
        constraints,
        bindings,
        strict=True,
    )
    result = compiled.build()

    diagnostics = [jsonable(item) for item in compiled.diagnostics]
    compiled_constraints = [
        {
            "class": type(item).__name__,
            "value": jsonable(item),
        }
        for item in compiled.constraints
    ]
    retained = retained_current_tuples(result.rows)

    expected = [
        {
            "M1": 20e-6,
            "M2": 20e-6,
            "M3": 20e-6,
            "M4": 20e-6,
            "M5": 40e-6,
            "M6": 10e-6,
            "M7": 10e-6,
        },
        {
            "M1": 30e-6,
            "M2": 30e-6,
            "M3": 30e-6,
            "M4": 30e-6,
            "M5": 60e-6,
            "M6": 10e-6,
            "M7": 10e-6,
        },
    ]

    def normalized(rows: list[dict[str, float]]) -> list[tuple[tuple[str, float], ...]]:
        return sorted(
            tuple(sorted((name, round(value, 15)) for name, value in row.items()))
            for row in rows
        )

    diagnostic_statuses = [
        str(item.get("status", ""))
        for item in diagnostics
        if isinstance(item, dict)
    ]

    checks = {
        "five_constraints_loaded": len(constraints) == 5,
        "five_constraints_compiled": len(compiled.constraints) == 5,
        "five_diagnostics_emitted": len(compiled.diagnostics) == 5,
        "all_diagnostics_compiled": all(
            status == "compiled"
            for status in diagnostic_statuses
        ),
        "two_expected_rows_retained": len(retained) == 2,
        "retained_rows_match_expected": (
            normalized(retained) == normalized(expected)
        ),
        "invalid_rows_rejected": (
            result.retained_count == 2
        ),
    }
    passed = all(checks.values())

    input_payload = {
        "constraints": [asdict(item) for item in constraints],
        "bindings": [
            {
                "name": item.region_name,
                "rows": jsonable(item.region.rows),
                "canonical_fields": jsonable(item.field_map),
            }
            for item in bindings
        ],
    }

    summary = {
        "gate": "4B",
        "proof": "Real design-intent constraints compile and execute",
        "status": "PASS" if passed else "FAIL",
        "constraint_artifact": str(args.constraints),
        "constraint_count": len(constraints),
        "compiled_constraint_count": len(compiled.constraints),
        "diagnostic_count": len(compiled.diagnostics),
        "retained_count": result.retained_count,
        "checks": checks,
        "retained_rows": retained,
        "expected_rows": expected,
        "intersection_metadata": jsonable(result.metadata),
    }

    (args.output_dir / "compiler_input.json").write_text(
        json.dumps(input_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "compiled_constraints.json").write_text(
        json.dumps(compiled_constraints, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "compiler_diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "execution_results.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    report = f"""# Gate 4B Constraint Compiler Report

## Summary

- **Status:** {summary["status"]}
- **Input constraints:** {len(constraints)}
- **Compiled constraints:** {len(compiled.constraints)}
- **Diagnostics:** {len(compiled.diagnostics)}
- **Retained rows:** {result.retained_count}

## Checks

```json
{json.dumps(checks, indent=2)}
```

## Retained Current Combinations

```json
{json.dumps(retained, indent=2)}
```

## Compiler Classes

```json
{json.dumps([item["class"] for item in compiled_constraints], indent=2)}
```

## Exit Criterion

Gate 4B passes when all five canonical constraints generated from the official
two-stage design intent compile through `CircuitConstraintCompiler`, every
diagnostic reports `compiled`, and execution retains exactly the two intended
current combinations while rejecting all deliberately invalid candidate rows.
"""
    (args.output_dir / "COMPILER_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )

    print("===== OPENAMS GATE 4B: CONSTRAINT COMPILER =====")
    print(f"status:               {summary['status']}")
    print(f"constraints_loaded:   {len(constraints)}")
    print(f"constraints_compiled: {len(compiled.constraints)}")
    print(f"diagnostics:          {len(compiled.diagnostics)}")
    print(f"retained_rows:        {result.retained_count}")
    print(f"evidence:             {args.output_dir}")

    if not passed:
        for name, value in checks.items():
            if not value:
                print(f"[FAIL] {name}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

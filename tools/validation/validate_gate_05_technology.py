#!/usr/bin/env python3
"""Gate 5 validation for the real SKY130 characterization table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openams.adapters import load_characterization_table_csv
from openams.io import load_yaml_mapping
from openams.metadata import normalize_project_inputs
from openams.technology import (
    TechnologyLookupRequest,
    TechnologyQuantity,
)
from openams.technology.table import TableTechnologyBackend


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Project input directory containing the OpenAMS input metadata.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/validation/evidence/gate_05_technology"),
    )
    return parser.parse_args()


def lookup_payload(backend, point):
    requested = {
        TechnologyQuantity.ID,
        TechnologyQuantity.GM,
        TechnologyQuantity.GDS,
        TechnologyQuantity.VTH,
        TechnologyQuantity.VDSAT,
    }
    result = backend.lookup(
        TechnologyLookupRequest(
            operating_point=point.operating_point,
            quantities=requested,
            require_saturation=True,
        )
    )
    return {
        "model": point.operating_point.model.name,
        "polarity": point.operating_point.model.polarity.value,
        "length_m": point.operating_point.length_m,
        "width_m": point.operating_point.width_m,
        "vgs_v": point.operating_point.vgs_v,
        "vds_v": point.operating_point.vds_v,
        "vbs_v": point.operating_point.vbs_v,
        "region": result.region.value,
        "values": {
            quantity.value: value
            for quantity, value in result.values.items()
        },
        "diagnostics": dict(result.diagnostics),
    }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    project = normalize_project_inputs(
        specifications=load_yaml_mapping(args.input_dir / "specs.yaml"),
        design_intent=load_yaml_mapping(args.input_dir / "design_intent.yaml"),
        design_rules=load_yaml_mapping(args.input_dir / "design_rules.yaml"),
        simulation=load_yaml_mapping(args.input_dir / "simulation.yaml"),
    )

    source_path = (
        args.input_dir / project.technology.active.source
    ).resolve()

    table = load_characterization_table_csv(
        source_path,
        technology_name=project.technology.active_source,
    )
    backend = TableTechnologyBackend(table)

    saturated_nmos = next(
        point
        for point in table.points
        if point.operating_point.model.polarity.value == "nmos"
        and point.region.value == "saturation"
    )
    saturated_pmos = next(
        point
        for point in table.points
        if point.operating_point.model.polarity.value == "pmos"
        and point.region.value == "saturation"
    )

    nmos_lookup = lookup_payload(backend, saturated_nmos)
    pmos_lookup = lookup_payload(backend, saturated_pmos)

    checks = {
        "source_exists": source_path.is_file(),
        "provider_is_inverse_table": (
            project.technology.active.provider == "mos_inverse_table"
        ),
        "row_count_nonzero": len(table.points) > 0,
        "both_polarities_supported": {
            item.value for item in table.capabilities.polarities
        } == {"nmos", "pmos"},
        "required_quantities_supported": {
            "id", "gm", "gds", "vth", "vdsat"
        }.issubset(
            {
                item.value
                for item in table.capabilities.quantities
            }
        ),
        "nmos_lookup_saturated": (
            nmos_lookup["region"] == "saturation"
        ),
        "pmos_lookup_saturated": (
            pmos_lookup["region"] == "saturation"
        ),
        "nmos_exact_lookup": (
            nmos_lookup["diagnostics"]["lookup_method"]
            == "exact_table_match"
        ),
        "pmos_exact_lookup": (
            pmos_lookup["diagnostics"]["lookup_method"]
            == "exact_table_match"
        ),
    }
    passed = all(checks.values())

    summary = {
        "gate": 5,
        "proof": "Real SKY130 table loaded and queried",
        "status": "PASS" if passed else "FAIL",
        "source_path": str(source_path),
        "provider": project.technology.active.provider,
        "technology_name": table.identity.name,
        "row_count": len(table.points),
        "capabilities": {
            "polarities": sorted(
                item.value for item in table.capabilities.polarities
            ),
            "quantities": sorted(
                item.value for item in table.capabilities.quantities
            ),
            "saturation_classification": (
                table.capabilities.saturation_classification
            ),
            "derivatives": table.capabilities.derivatives,
        },
        "nmos_lookup": nmos_lookup,
        "pmos_lookup": pmos_lookup,
        "checks": checks,
    }

    (args.output_dir / "technology_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    report = f"""# Gate 5 Technology Validation Report

## Summary

- **Status:** {summary["status"]}
- **Source:** `{source_path}`
- **Provider:** `{summary["provider"]}`
- **Rows:** {summary["row_count"]}

## Checks

```json
{json.dumps(checks, indent=2)}
```

## NMOS Exact Lookup

```json
{json.dumps(nmos_lookup, indent=2)}
```

## PMOS Exact Lookup

```json
{json.dumps(pmos_lookup, indent=2)}
```

## Exit Criterion

Gate 5 passes when the active metadata source resolves to the real SKY130 CSV,
the CSV adapter constructs a validated `CharacterizationTable`, and exact
saturated NMOS and PMOS lookups return ID, GM, GDS, VTH, and VDSAT through the
production `TableTechnologyBackend`.
"""
    (args.output_dir / "TECHNOLOGY_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )

    print("===== OPENAMS GATE 5: TECHNOLOGY =====")
    print(f"status:       {summary['status']}")
    print(f"source:       {source_path}")
    print(f"rows:         {len(table.points)}")
    print(f"NMOS model:   {nmos_lookup['model']}")
    print(f"PMOS model:   {pmos_lookup['model']}")
    print(f"evidence:     {args.output_dir}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

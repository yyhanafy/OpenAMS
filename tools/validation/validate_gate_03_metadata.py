#!/usr/bin/env python3
"""Gate 3 validator for OpenAMS metadata serialization and normalization."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from openams.io import load_yaml_mapping
from openams.metadata import MetadataValidationError, normalize_project_inputs


def thaw(value: Any) -> Any:
    """Convert immutable/nested metadata containers into JSON-safe values."""

    if isinstance(value, Mapping):
        return {str(key): thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((thaw(item) for item in value), key=repr)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/validation/evidence/gate_03_metadata"),
    )
    parser.add_argument(
        "--migrate-technology-schema",
        action="store_true",
        help="Migrate active_technology_table/technology_tables to the current schema.",
    )
    return parser.parse_args()


def migrate_design_rules(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"design rules root must be a mapping: {path}")

    if "active_technology_source" in data and "technology_sources" in data:
        return {
            "performed": False,
            "reason": "already_current",
            "backup": None,
        }

    active = data.pop("active_technology_table", None)
    tables = data.pop("technology_tables", None)

    if not isinstance(active, str) or not active.strip():
        raise SystemExit(
            "cannot migrate: missing non-empty active_technology_table"
        )
    if not isinstance(tables, dict) or not tables:
        raise SystemExit(
            "cannot migrate: missing non-empty technology_tables"
        )

    sources: dict[str, Any] = {}
    for name, entry in tables.items():
        if not isinstance(entry, dict):
            raise SystemExit(
                f"cannot migrate: technology table {name!r} is not a mapping"
            )

        provider = entry.get("provider")
        source = entry.get("source", entry.get("path"))

        if not isinstance(provider, str) or not provider.strip():
            raise SystemExit(
                f"cannot migrate: technology table {name!r} has no provider"
            )
        if not isinstance(source, str) or not source.strip():
            raise SystemExit(
                f"cannot migrate: technology table {name!r} has no source/path"
            )

        migrated = {
            "provider": provider,
            "source": source,
        }
        for key, value in entry.items():
            if key not in {"provider", "source", "path"}:
                migrated[key] = value
        sources[str(name)] = migrated

    backup = path.with_name(path.name + ".before_gate3_migration")
    if not backup.exists():
        shutil.copy2(path, backup)

    data["active_technology_source"] = active
    data["technology_sources"] = sources

    path.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )

    return {
        "performed": True,
        "reason": "legacy_schema_migrated",
        "backup": str(backup),
        "active_technology_source": active,
        "technology_source_names": sorted(sources),
    }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "specifications": args.input_dir / "specs.yaml",
        "design_intent": args.input_dir / "design_intent.yaml",
        "design_rules": args.input_dir / "design_rules.yaml",
        "simulation": args.input_dir / "simulation.yaml",
    }

    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise SystemExit("missing metadata files:\n  " + "\n  ".join(missing))

    migration = {
        "performed": False,
        "reason": "not_requested",
        "backup": None,
    }
    if args.migrate_technology_schema:
        migration = migrate_design_rules(files["design_rules"])

    loaded: dict[str, Any] = {}
    serialization_checks: dict[str, bool] = {}
    for name, path in files.items():
        document = load_yaml_mapping(path)
        loaded[name] = document
        serialization_checks[f"{name}_loaded"] = True
        serialization_checks[f"{name}_root_is_mapping"] = isinstance(document, dict)
        shutil.copy2(path, raw_dir / path.name)

    normalization_error: str | None = None
    project = None
    try:
        project = normalize_project_inputs(**loaded)
    except MetadataValidationError as exc:
        normalization_error = str(exc)

    passed = normalization_error is None

    summary = {
        "gate": 3,
        "proof": "Metadata serialized and normalized into ProjectInputs",
        "status": "PASS" if passed else "BLOCKED",
        "input_dir": str(args.input_dir),
        "pyyaml_version": yaml.__version__,
        "migration": migration,
        "serialization_checks": serialization_checks,
        "document_keys": {
            name: list(document.keys())
            for name, document in loaded.items()
        },
        "normalization_error": normalization_error,
        "technology": None,
    }

    if project is not None:
        summary["technology"] = {
            "active_source": project.technology.active_source,
            "provider": project.technology.active.provider,
            "source": project.technology.active.source,
            "options": thaw(project.technology.active.options),
        }

    (args.output_dir / "metadata_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    report = f"""# Gate 3 Metadata Validation Report

## Summary

- **Gate:** 3
- **Status:** {summary["status"]}
- **Input directory:** `{args.input_dir}`
- **PyYAML:** `{yaml.__version__}`

## Serialization

```json
{json.dumps(serialization_checks, indent=2)}
```

## Document Root Keys

```json
{json.dumps(summary["document_keys"], indent=2)}
```

## Technology Schema Migration

```json
{json.dumps(migration, indent=2)}
```

## Semantic Normalization

- **Error:** `{normalization_error or "None"}`

## Normalized Technology

```json
{json.dumps(summary["technology"], indent=2, default=str)}
```

## Exit Criterion

Gate 3 passes when all four YAML documents load as mappings and
`normalize_project_inputs()` returns an immutable `ProjectInputs` object using
the current technology metadata schema.
"""
    (args.output_dir / "METADATA_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )

    print("===== OPENAMS GATE 3: METADATA =====")
    print(f"status:       {summary['status']}")
    print(f"PyYAML:       {yaml.__version__}")
    print(f"migration:    {migration['reason']}")
    print(f"normalization:{' PASS' if passed else ' BLOCKED'}")
    if normalization_error:
        print(f"reason:       {normalization_error}")
    else:
        print(
            "technology:   "
            f"{project.technology.active_source} / "
            f"{project.technology.active.provider}"
        )
    print(f"evidence:     {args.output_dir}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

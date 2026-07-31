#!/usr/bin/env python3
"""Validate recursive hierarchy parsing using the folded-cascode example."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from openams.io import load_spice_hierarchy
from openams.topology import (
    expand_spice_hierarchy_sources,
    parse_spice_hierarchy_sources,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root-netlist",
        type=Path,
        default=Path(
            "examples/folded_cascode/inputs/folded_cascode.spice"
        ),
    )
    parser.add_argument(
        "--top-subcircuit",
        default="folded_cascode_ota",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "docs/validation/evidence/hierarchical_parser"
        ),
    )
    return parser.parse_args()


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    loaded = load_spice_hierarchy(
        args.root_netlist,
        include_search_roots=(args.root_netlist.parent,),
    )

    expansion = expand_spice_hierarchy_sources(
        loaded.sources,
        top_subcircuit=args.top_subcircuit,
    )

    circuit = parse_spice_hierarchy_sources(
        loaded.sources,
        top_subcircuit=args.top_subcircuit,
    )

    devices = [
        {
            "name": name,
            "kind": enum_value(device.kind),
            "model": device.model,
            "terminals": dict(device.terminals),
            "parameters": dict(device.parameters),
        }
        for name, device in circuit.devices.items()
    ]

    kind_counts = Counter(item["kind"] for item in devices)
    mos_count = sum(
        "mos" in item["kind"].lower()
        for item in devices
    )

    checks = {
        "source_file_count_is_8": len(loaded.source_paths) == 8,
        "subcircuit_count_is_8": len(expansion.subcircuits) == 8,
        "expanded_child_instance_count_is_7": (
            expansion.expanded_instance_count == 7
        ),
        "primitive_device_count_is_16": (
            expansion.primitive_device_count == 16
        ),
        "canonical_device_count_is_16": len(circuit.devices) == 16,
        "mos_count_is_11": mos_count == 11,
    }

    passed = all(checks.values())

    summary = {
        "status": "PASS" if passed else "FAIL",
        "source_files": list(loaded.source_paths),
        "subcircuits": sorted(
            definition.name
            for definition in expansion.subcircuits.values()
        ),
        "expanded_instance_count": (
            expansion.expanded_instance_count
        ),
        "primitive_device_count": (
            expansion.primitive_device_count
        ),
        "canonical_device_count": len(circuit.devices),
        "node_count": len(circuit.nodes),
        "mos_count": mos_count,
        "device_kind_counts": dict(sorted(kind_counts.items())),
        "checks": checks,
    }

    (args.output_dir / "flattened_folded_cascode.spice").write_text(
        expansion.flattened_spice,
        encoding="utf-8",
    )

    (args.output_dir / "hierarchy_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    (args.output_dir / "topology.json").write_text(
        json.dumps(
            {
                "name": circuit.name,
                "devices": devices,
                "nodes": sorted(circuit.nodes),
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    print("===== OPENAMS RECURSIVE HIERARCHY VALIDATION =====")
    print(f"status:              {summary['status']}")
    print(f"source_files:        {len(loaded.source_paths)}")
    print(f"subcircuits:         {len(expansion.subcircuits)}")
    print(
        f"expanded_instances:  "
        f"{expansion.expanded_instance_count}"
    )
    print(
        f"primitive_devices:   "
        f"{expansion.primitive_device_count}"
    )
    print(f"MOS devices:         {mos_count}")
    print(f"canonical nodes:     {len(circuit.nodes)}")
    print(f"evidence:            {args.output_dir}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

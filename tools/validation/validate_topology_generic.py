#!/usr/bin/env python3
"""Generic OpenAMS flat-SPICE subcircuit topology validator."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from openams.topology import extract_spice_subcircuit, parse_spice_subcircuit


def parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse and validate a named flat-SPICE subcircuit without "
            "assuming a particular circuit topology."
        )
    )
    parser.add_argument(
        "--netlist",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--subcircuit",
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-ports",
        help="Comma-separated ordered subcircuit ports.",
    )
    parser.add_argument(
        "--expected-devices",
        help="Comma-separated expected device instance names.",
    )
    parser.add_argument(
        "--expected-device-count",
        type=int,
    )
    parser.add_argument(
        "--expected-mos-count",
        type=int,
    )
    return parser.parse_args()


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def main() -> int:
    args = parse_args()

    if not args.netlist.is_file():
        raise SystemExit(f"netlist does not exist: {args.netlist}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    text = args.netlist.read_text(encoding="utf-8")

    selected = extract_spice_subcircuit(
        text,
        subcircuit=args.subcircuit,
    )
    circuit = parse_spice_subcircuit(
        text,
        subcircuit=args.subcircuit,
    )

    device_rows: list[dict[str, Any]] = []

    for name, device in circuit.devices.items():
        device_rows.append(
            {
                "name": name,
                "kind": enum_value(device.kind),
                "model": device.model,
                "terminals": dict(device.terminals),
                "parameters": dict(device.parameters),
            }
        )

    node_rows = [{"name": name} for name in circuit.nodes]
    kind_counts = Counter(row["kind"] for row in device_rows)

    actual_devices = set(circuit.devices)
    expected_devices = set(parse_csv(args.expected_devices))
    expected_ports = parse_csv(args.expected_ports)

    missing_devices = sorted(expected_devices - actual_devices)
    unexpected_devices = sorted(actual_devices - expected_devices)

    mos_kinds = {
        "mos",
        "mosfet",
        "nmos",
        "pmos",
    }

    mos_rows = [
        row
        for row in device_rows
        if row["kind"].lower() in mos_kinds
        or str(row.get("model", "")).lower().find("nfet") >= 0
        or str(row.get("model", "")).lower().find("pfet") >= 0
    ]

    checks: dict[str, bool] = {
        "parser_succeeded": True,
        "subcircuit_name_matches": circuit.name == args.subcircuit,
        "subcircuit_has_ports": bool(selected.ports),
        "subcircuit_has_devices": bool(device_rows),
        "subcircuit_has_nodes": bool(node_rows),
        "all_devices_have_terminals": all(
            bool(row["terminals"])
            for row in device_rows
        ),
    }

    if expected_ports:
        checks["ports_match"] = tuple(selected.ports) == expected_ports

    if expected_devices:
        checks["expected_devices_present"] = not missing_devices
        checks["no_unexpected_devices"] = not unexpected_devices

    if args.expected_device_count is not None:
        checks["device_count_matches"] = (
            len(device_rows) == args.expected_device_count
        )

    if args.expected_mos_count is not None:
        checks["mos_count_matches"] = (
            len(mos_rows) == args.expected_mos_count
        )

    passed = all(checks.values())

    topology = {
        "artifact": "openams.topology",
        "schema_version": 1,
        "circuit_name": circuit.name,
        "subcircuit_ports": list(selected.ports),
        "source_lines": {
            "start": selected.start_line,
            "end": selected.end_line,
        },
        "device_count": len(device_rows),
        "mos_device_count": len(mos_rows),
        "node_count": len(node_rows),
        "devices": device_rows,
        "nodes": node_rows,
    }

    summary = {
        "gate": 2,
        "validator": "generic_flat_spice_topology",
        "proof": (
            "Named flat-SPICE subcircuit parsed into the canonical "
            "OpenAMS Circuit representation."
        ),
        "status": "PASS" if passed else "FAIL",
        "source_netlist": str(args.netlist),
        "subcircuit": args.subcircuit,
        "ports": list(selected.ports),
        "device_count": len(device_rows),
        "mos_device_count": len(mos_rows),
        "node_count": len(node_rows),
        "device_kind_counts": dict(sorted(kind_counts.items())),
        "expected_ports": list(expected_ports),
        "expected_devices": sorted(expected_devices),
        "missing_devices": missing_devices,
        "unexpected_devices": unexpected_devices,
        "checks": checks,
    }

    (args.output_dir / "topology.json").write_text(
        json.dumps(topology, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    (args.output_dir / "topology_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    (raw_dir / "netlist.spice").write_text(
        text,
        encoding="utf-8",
    )

    (raw_dir / "selected_subcircuit.spice").write_text(
        selected.body,
        encoding="utf-8",
    )

    report = f"""# Generic Gate 2 Topology Validation Report

## Summary

- **Gate:** 2
- **Status:** {summary["status"]}
- **Netlist:** `{args.netlist}`
- **Subcircuit:** `{args.subcircuit}`
- **Ports:** `{", ".join(selected.ports)}`
- **Devices:** {len(device_rows)}
- **MOS devices:** {len(mos_rows)}
- **Nodes:** {len(node_rows)}

## Device Coverage

- **Missing:** `{", ".join(missing_devices) if missing_devices else "None"}`
- **Unexpected:** `{", ".join(unexpected_devices) if unexpected_devices else "None"}`

## Checks

```json
{json.dumps(checks, indent=2)}

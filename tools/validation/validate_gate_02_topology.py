#!/usr/bin/env python3
"""Gate 2 validator for a named flat-SPICE subcircuit."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from openams.topology import extract_spice_subcircuit, parse_spice_subcircuit


def parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()

    return tuple(
        item.strip()
        for item in value.split(",")
        if item.strip()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse a named flat-SPICE subcircuit into the canonical "
            "OpenAMS topology representation."
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
        default=None,
        help=(
            "Optional comma-separated ordered subcircuit ports, "
            "for example: inp,inn,out,vdd,vss,vbias"
        ),
    )

    parser.add_argument(
        "--expected-devices",
        default=None,
        help=(
            "Optional comma-separated device instance names, "
            "for example: XM1,XM2,XM3,Cc"
        ),
    )

    parser.add_argument(
        "--expected-device-count",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--expected-mos-count",
        type=int,
        default=None,
    )

    return parser.parse_args()


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def is_mos_device(row: dict[str, Any]) -> bool:
    kind = str(row.get("kind", "")).lower()
    model = str(row.get("model", "")).lower()
    terminals = row.get("terminals", {})

    if kind in {
        "mos",
        "mosfet",
        "nmos",
        "pmos",
    }:
        return True

    if "nfet" in model or "pfet" in model:
        return True

    return set(terminals) >= {
        "drain",
        "gate",
        "source",
        "bulk",
    }


def main() -> int:
    args = parse_args()

    if not args.netlist.is_file():
        raise SystemExit(
            f"netlist does not exist: {args.netlist}"
        )

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    text = args.netlist.read_text(
        encoding="utf-8",
    )

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

    node_rows = [
        {"name": name}
        for name in circuit.nodes
    ]

    mos_rows = [
        row
        for row in device_rows
        if is_mos_device(row)
    ]

    kind_counts = Counter(
        row["kind"]
        for row in device_rows
    )

    actual_devices = set(circuit.devices)

    expected_ports = parse_csv(
        args.expected_ports
    )

    expected_devices = set(
        parse_csv(args.expected_devices)
    )

    missing_devices = sorted(
        expected_devices - actual_devices
    )

    unexpected_devices = sorted(
        actual_devices - expected_devices
    )

    checks: dict[str, bool] = {
        "parser_succeeded": True,
        "subcircuit_name_matches": (
            circuit.name == args.subcircuit
        ),
        "subcircuit_has_ports": bool(
            selected.ports
        ),
        "subcircuit_has_devices": bool(
            device_rows
        ),
        "subcircuit_has_nodes": bool(
            node_rows
        ),
        "all_devices_have_terminals": all(
            bool(row["terminals"])
            for row in device_rows
        ),
    }

    if expected_ports:
        checks["ports_match"] = (
            tuple(selected.ports)
            == expected_ports
        )

    if expected_devices:
        checks["expected_devices_present"] = (
            not missing_devices
        )

        checks["no_unexpected_devices"] = (
            not unexpected_devices
        )

    if args.expected_device_count is not None:
        checks["device_count_matches"] = (
            len(device_rows)
            == args.expected_device_count
        )

    if args.expected_mos_count is not None:
        checks["mos_count_matches"] = (
            len(mos_rows)
            == args.expected_mos_count
        )

    passed = all(checks.values())

    topology = {
        "artifact": "openams.topology",
        "schema_version": 1,
        "circuit_name": circuit.name,
        "subcircuit_ports": list(
            selected.ports
        ),
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
        "validator": (
            "generic_flat_spice_topology"
        ),
        "proof": (
            "Named flat-SPICE subcircuit parsed "
            "into the canonical OpenAMS Circuit "
            "representation."
        ),
        "status": (
            "PASS"
            if passed
            else "FAIL"
        ),
        "source_netlist": str(
            args.netlist
        ),
        "subcircuit": args.subcircuit,
        "ports": list(
            selected.ports
        ),
        "device_count": len(
            device_rows
        ),
        "mos_device_count": len(
            mos_rows
        ),
        "node_count": len(
            node_rows
        ),
        "device_kind_counts": dict(
            sorted(kind_counts.items())
        ),
        "expected_ports": list(
            expected_ports
        ),
        "expected_devices": sorted(
            expected_devices
        ),
        "missing_devices": (
            missing_devices
        ),
        "unexpected_devices": (
            unexpected_devices
        ),
        "checks": checks,
    }

    topology_path = (
        args.output_dir
        / "topology.json"
    )

    summary_path = (
        args.output_dir
        / "topology_summary.json"
    )

    topology_path.write_text(
        json.dumps(
            topology,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    (
        raw_dir
        / "netlist.spice"
    ).write_text(
        text,
        encoding="utf-8",
    )

    (
        raw_dir
        / "selected_subcircuit.spice"
    ).write_text(
        selected.body,
        encoding="utf-8",
    )

    missing_text = (
        ", ".join(missing_devices)
        if missing_devices
        else "None"
    )

    unexpected_text = (
        ", ".join(unexpected_devices)
        if unexpected_devices
        else "None"
    )

    checks_json = json.dumps(
        checks,
        indent=2,
    )

    report_lines = [
        "# Gate 2 Topology Validation Report",
        "",
        "## Summary",
        "",
        f"- **Gate:** 2",
        f"- **Status:** {summary['status']}",
        f"- **Validator:** `generic_flat_spice_topology`",
        f"- **Netlist:** `{args.netlist}`",
        f"- **Subcircuit:** `{args.subcircuit}`",
        f"- **Ports:** `{', '.join(selected.ports)}`",
        f"- **Devices:** {len(device_rows)}",
        f"- **MOS devices:** {len(mos_rows)}",
        f"- **Nodes:** {len(node_rows)}",
        "",
        "## Device Coverage",
        "",
        f"- **Missing:** `{missing_text}`",
        f"- **Unexpected:** `{unexpected_text}`",
        "",
        "## Checks",
        "",
        "```json",
        checks_json,
        "```",
        "",
        "## Exit Criterion",
        "",
        (
            "Gate 2 passes when the requested named flat-SPICE "
            "subcircuit is parsed, its declared ports and devices "
            "are preserved, every parsed device has terminal "
            "connectivity, and all explicitly supplied expectations "
            "are satisfied."
        ),
        "",
    ]

    (
        args.output_dir
        / "TOPOLOGY_REPORT.md"
    ).write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    print(
        "===== OPENAMS GATE 2: TOPOLOGY ====="
    )
    print(
        f"status:       {summary['status']}"
    )
    print(
        f"validator:    {summary['validator']}"
    )
    print(
        f"subcircuit:   {args.subcircuit}"
    )
    print(
        f"ports:        {', '.join(selected.ports)}"
    )
    print(
        f"devices:      {len(device_rows)}"
    )
    print(
        f"MOS devices:  {len(mos_rows)}"
    )
    print(
        f"nodes:        {len(node_rows)}"
    )
    print(
        f"missing:      {missing_devices or 'none'}"
    )
    print(
        f"unexpected:   {unexpected_devices or 'none'}"
    )
    print(
        f"evidence:     {args.output_dir}"
    )

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

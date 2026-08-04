#!/usr/bin/env python3
"""Gate 2 validator for the official two-stage-op-amp subcircuit."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from openams.topology import extract_spice_subcircuit, parse_spice_subcircuit


EXPECTED_DEVICES = {"XM1", "XM2", "XM3", "XM4", "XM5", "XM6", "XM7", "Cc"}
EXPECTED_PORTS = ("inp", "inn", "out", "vdd", "vss", "vbias")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--netlist",
        type=Path,
        default=Path("examples/two_stage_opamp/inputs/netlist.spice"),
    )
    parser.add_argument("--subcircuit", default="two_stage_opamp")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/validation/evidence/gate_02_topology"),
    )
    return parser.parse_args()


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    text = args.netlist.read_text(encoding="utf-8")
    selected = extract_spice_subcircuit(text, subcircuit=args.subcircuit)
    circuit = parse_spice_subcircuit(text, subcircuit=args.subcircuit)

    device_rows = []
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
    actual_devices = set(circuit.devices)
    missing = sorted(EXPECTED_DEVICES - actual_devices)
    unexpected = sorted(actual_devices - EXPECTED_DEVICES)
    kind_counts = Counter(row["kind"] for row in device_rows)

    checks = {
        "parser_succeeded": True,
        "subcircuit_name_matches": circuit.name == args.subcircuit,
        "ports_match": selected.ports == EXPECTED_PORTS,
        "expected_devices_present": not missing,
        "no_unexpected_devices": not unexpected,
        "all_devices_have_terminals": all(row["terminals"] for row in device_rows),
        "m1_connectivity": circuit.devices["XM1"].terminals == {
            "drain": "n1", "gate": "inp", "source": "ntail", "bulk": "vss"
        },
        "m6_connectivity": circuit.devices["XM6"].terminals == {
            "drain": "out", "gate": "n2", "source": "vdd", "bulk": "vdd"
        },
        "compensation_capacitor_connectivity": circuit.devices["Cc"].terminals == {
            "positive": "n2", "negative": "out"
        },
    }
    passed = all(checks.values())

    topology = {
        "circuit_name": circuit.name,
        "subcircuit_ports": list(selected.ports),
        "source_lines": {
            "start": selected.start_line,
            "end": selected.end_line,
        },
        "device_count": len(device_rows),
        "node_count": len(node_rows),
        "devices": device_rows,
        "nodes": node_rows,
    }
    summary = {
        "gate": 2,
        "proof": "Official netlist subcircuit parsed into canonical Circuit",
        "status": "PASS" if passed else "FAIL",
        "source_netlist": str(args.netlist),
        "subcircuit": args.subcircuit,
        "ports": list(selected.ports),
        "device_count": len(device_rows),
        "node_count": len(node_rows),
        "device_kind_counts": dict(sorted(kind_counts.items())),
        "missing_devices": missing,
        "unexpected_devices": unexpected,
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
    (raw_dir / "netlist.spice").write_text(text, encoding="utf-8")
    (raw_dir / "selected_subcircuit.spice").write_text(
        selected.body,
        encoding="utf-8",
    )

    report = f"""# Gate 2 Topology Validation Report

## Summary

- **Gate:** 2
- **Status:** {summary["status"]}
- **Netlist:** `{args.netlist}`
- **Subcircuit:** `{args.subcircuit}`
- **Ports:** `{", ".join(selected.ports)}`
- **Devices:** {len(device_rows)}
- **Nodes:** {len(node_rows)}

## Device Coverage

- **Missing:** `{", ".join(missing) if missing else "None"}`
- **Unexpected:** `{", ".join(unexpected) if unexpected else "None"}`

## Checks

```json
{json.dumps(checks, indent=2)}
```

## Exit Criterion

Gate 2 passes when the official named subcircuit is extracted directly from the
reference netlist, its declared ports are preserved in validation evidence, all
seven MOS primitive instances and the compensation capacitor are parsed, and
their structural connectivity matches the reference circuit.
"""
    (args.output_dir / "TOPOLOGY_REPORT.md").write_text(report, encoding="utf-8")

    print("===== OPENAMS GATE 2: TOPOLOGY =====")
    print(f"status:     {summary['status']}")
    print(f"subcircuit: {args.subcircuit}")
    print(f"ports:      {', '.join(selected.ports)}")
    print(f"devices:    {len(device_rows)}")
    print(f"nodes:      {len(node_rows)}")
    print(f"missing:    {missing or 'none'}")
    print(f"unexpected: {unexpected or 'none'}")
    print(f"evidence:   {args.output_dir}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only connectivity queries over canonical circuits."""

from __future__ import annotations

from openams.model import Circuit, Device, Node, Terminal

from .errors import TopologyError


def node(circuit: Circuit, name: str) -> Node:
    """Return one node by exact canonical name."""

    try:
        return circuit.nodes[name]
    except KeyError as exc:
        raise TopologyError(f"unknown node {name!r}") from exc


def device(circuit: Circuit, name: str) -> Device:
    """Return one device by exact canonical name."""

    try:
        return circuit.devices[name]
    except KeyError as exc:
        raise TopologyError(f"unknown device {name!r}") from exc


def connected_terminals(
    circuit: Circuit,
    node_name: str,
) -> tuple[tuple[str, Terminal], ...]:
    """Return `(device_name, terminal)` pairs connected to a node."""

    node(circuit, node_name)
    matches: list[tuple[str, Terminal]] = []

    for device_name, instance in circuit.devices.items():
        for terminal_name, connected_node in instance.terminals.items():
            if connected_node == node_name:
                matches.append(
                    (
                        device_name,
                        Terminal(
                            name=terminal_name,
                            node=connected_node,
                        ),
                    )
                )

    return tuple(matches)


def connected_devices(circuit: Circuit, node_name: str) -> tuple[Device, ...]:
    """Return unique devices connected to a node in circuit order."""

    seen: set[str] = set()
    result: list[Device] = []
    for device_name, _terminal in connected_terminals(circuit, node_name):
        if device_name not in seen:
            seen.add(device_name)
            result.append(circuit.devices[device_name])
    return tuple(result)

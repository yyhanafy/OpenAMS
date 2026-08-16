"""Pure recursive SPICE hierarchy expansion.

This module performs no filesystem access. Callers provide already-loaded
SPICE source texts keyed by stable source identifiers.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Iterable, Mapping

from openams.model import Circuit

from .errors import MalformedElementError, UnsupportedHierarchyError
from .spice_parser import parse_spice_circuit


_MOS_HINTS = ("nfet", "pfet", "nmos", "pmos", "mos")
_INCLUDE_RE = re.compile(r"^\s*\.include\s+(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class SubcircuitDefinition:
    name: str
    ports: tuple[str, ...]
    defaults: Mapping[str, str]
    body_lines: tuple[str, ...]
    source_name: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class HierarchyExpansion:
    top_subcircuit: str
    flattened_spice: str
    subcircuits: Mapping[str, SubcircuitDefinition]
    source_names: tuple[str, ...]
    expanded_instance_count: int
    primitive_device_count: int


def logical_spice_lines(text: str) -> Iterable[tuple[int, str]]:
    current = ""
    start = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("*"):
            continue
        if stripped.startswith("+"):
            if not current:
                raise MalformedElementError(
                    f"line {number}: continuation has no preceding line"
                )
            current += " " + stripped[1:].strip()
            continue
        if current:
            yield start, current
        current = stripped
        start = number
    if current:
        yield start, current


def included_source_tokens(text: str) -> tuple[str, ...]:
    """Return raw include targets declared by one SPICE source."""

    result: list[str] = []
    for _, line in logical_spice_lines(text):
        match = _INCLUDE_RE.match(line)
        if not match:
            continue
        try:
            tokens = shlex.split(match.group(1), comments=False, posix=True)
        except ValueError as exc:
            raise MalformedElementError(
                f"invalid .include declaration: {exc}"
            ) from exc
        if not tokens:
            raise MalformedElementError("empty .include declaration")
        result.append(tokens[0])
    return tuple(result)


def _tokens(line: str, *, source: str, line_number: int) -> list[str]:
    try:
        return shlex.split(line, comments=False, posix=True)
    except ValueError as exc:
        raise MalformedElementError(
            f"{source}:{line_number}: cannot tokenize SPICE line: {exc}"
        ) from exc


def _parameter_split(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    positional: list[str] = []
    parameters: dict[str, str] = {}
    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            parameters[key.strip().lower()] = value.strip()
        else:
            positional.append(token)
    return positional, parameters


def _parse_subcircuits(
    sources: Mapping[str, str],
) -> dict[str, SubcircuitDefinition]:
    definitions: dict[str, SubcircuitDefinition] = {}

    for source_name, text in sources.items():
        active_name: str | None = None
        active_ports: tuple[str, ...] = ()
        active_defaults: dict[str, str] = {}
        active_body: list[str] = []
        active_start = 0

        for line_number, line in logical_spice_lines(text):
            tokens = _tokens(line, source=source_name, line_number=line_number)
            directive = tokens[0].lower()

            if directive == ".include":
                continue

            if directive == ".subckt":
                if active_name is not None:
                    raise UnsupportedHierarchyError(
                        f"{source_name}:{line_number}: nested .subckt definitions are unsupported"
                    )
                if len(tokens) < 2:
                    raise MalformedElementError(
                        f"{source_name}:{line_number}: .subckt requires a name"
                    )
                positional, defaults = _parameter_split(tokens[1:])
                active_name = positional[0]
                active_ports = tuple(positional[1:])
                active_defaults = defaults
                active_body = []
                active_start = line_number
                continue

            if directive == ".ends":
                if active_name is None:
                    continue
                if len(tokens) > 1 and tokens[1].lower() != active_name.lower():
                    raise MalformedElementError(
                        f"{source_name}:{line_number}: .ends {tokens[1]!r} does not match "
                        f".subckt {active_name!r}"
                    )
                key = active_name.lower()
                if key in definitions:
                    raise UnsupportedHierarchyError(
                        f"duplicate subcircuit definition {active_name!r}"
                    )
                definitions[key] = SubcircuitDefinition(
                    name=active_name,
                    ports=active_ports,
                    defaults=dict(active_defaults),
                    body_lines=tuple(active_body),
                    source_name=source_name,
                    start_line=active_start,
                    end_line=line_number,
                )
                active_name = None
                active_ports = ()
                active_defaults = {}
                active_body = []
                continue

            if active_name is not None:
                active_body.append(line)

        if active_name is not None:
            raise MalformedElementError(
                f"{source_name}:{active_start}: subcircuit {active_name!r} has no matching .ends"
            )

    return definitions


def _primitive_hierarchical_name(local_name: str, path: tuple[str, ...]) -> str:
    if not path:
        return local_name
    return f"{local_name[0]}{'.'.join(path)}.{local_name[1:]}"


def _map_node(node: str, *, port_map: Mapping[str, str], path: tuple[str, ...]) -> str:
    if node in {"0", "gnd", "GND"}:
        return node
    if node in port_map:
        return port_map[node]
    if not path:
        return node
    return ".".join((*path, node))


def _is_primitive_mos_model(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _MOS_HINTS)


def expand_spice_hierarchy_sources(
    sources: Mapping[str, str],
    *,
    top_subcircuit: str,
) -> HierarchyExpansion:
    """Flatten one named top-level subcircuit from preloaded sources."""

    if not sources:
        raise UnsupportedHierarchyError("at least one SPICE source is required")

    library = _parse_subcircuits(sources)
    top_key = top_subcircuit.lower()
    if top_key not in library:
        raise UnsupportedHierarchyError(
            f"top-level subcircuit {top_subcircuit!r} was not found"
        )

    flattened: list[str] = []
    expanded_instances = 0
    recursion_stack: list[str] = []

    def expand(
        definition: SubcircuitDefinition,
        *,
        path: tuple[str, ...],
        port_map: Mapping[str, str],
    ) -> None:
        nonlocal expanded_instances

        key = definition.name.lower()
        if key in recursion_stack:
            cycle = " -> ".join((*recursion_stack, key))
            raise UnsupportedHierarchyError(
                f"recursive subcircuit cycle detected: {cycle}"
            )

        recursion_stack.append(key)
        try:
            for body_line in definition.body_lines:
                tokens = _tokens(
                    body_line,
                    source=definition.source_name,
                    line_number=definition.start_line,
                )
                if not tokens:
                    continue

                name = tokens[0]
                prefix = name[0].upper()

                if prefix != "X":
                    if prefix not in {"M", "R", "C", "V", "I"}:
                        raise UnsupportedHierarchyError(
                            f"{definition.source_name}: unsupported primitive {name!r}"
                        )
                    mapped = list(tokens)
                    mapped[0] = _primitive_hierarchical_name(name, path)

                    if prefix == "M":
                        if len(mapped) < 6:
                            raise MalformedElementError(
                                f"primitive MOS {name!r} has too few tokens"
                            )
                        for index in range(1, 5):
                            mapped[index] = _map_node(
                                mapped[index], port_map=port_map, path=path
                            )
                    else:
                        if len(mapped) < 4:
                            raise MalformedElementError(
                                f"primitive {name!r} has too few tokens"
                            )
                        mapped[1] = _map_node(mapped[1], port_map=port_map, path=path)
                        mapped[2] = _map_node(mapped[2], port_map=port_map, path=path)

                    flattened.append(" ".join(mapped))
                    continue

                positional, _parameters = _parameter_split(tokens[1:])
                if len(positional) < 2:
                    raise MalformedElementError(
                        f"hierarchical instance {name!r} has too few positional tokens"
                    )

                referenced = positional[-1]
                child_key = referenced.lower()

                if child_key not in library:
                    if not _is_primitive_mos_model(referenced):
                        raise UnsupportedHierarchyError(
                            f"instance {name!r} references unknown subcircuit/model "
                            f"{referenced!r}"
                        )
                    if len(positional) != 5:
                        raise UnsupportedHierarchyError(
                            f"primitive MOS instance {name!r} must have four nodes "
                            "and one model"
                        )
                    mapped_name = _primitive_hierarchical_name(name, path)
                    mapped_nodes = [
                        _map_node(node, port_map=port_map, path=path)
                        for node in positional[:4]
                    ]
                    parameter_tokens = [token for token in tokens[1:] if "=" in token]
                    flattened.append(
                        " ".join(
                            [mapped_name, *mapped_nodes, referenced, *parameter_tokens]
                        )
                    )
                    continue

                child = library[child_key]
                instance_nodes = positional[:-1]
                if len(instance_nodes) != len(child.ports):
                    raise UnsupportedHierarchyError(
                        f"instance {name!r} of {child.name!r} supplies "
                        f"{len(instance_nodes)} pins; expected {len(child.ports)}"
                    )

                mapped_nodes = [
                    _map_node(node, port_map=port_map, path=path)
                    for node in instance_nodes
                ]
                child_port_map = dict(zip(child.ports, mapped_nodes, strict=True))
                expanded_instances += 1
                expand(
                    child,
                    path=(*path, name),
                    port_map=child_port_map,
                )
        finally:
            recursion_stack.pop()

    top = library[top_key]
    expand(top, path=(), port_map={port: port for port in top.ports})

    flattened_text = "\n".join(flattened) + ("\n" if flattened else "")
    return HierarchyExpansion(
        top_subcircuit=top.name,
        flattened_spice=flattened_text,
        subcircuits=dict(library),
        source_names=tuple(sources),
        expanded_instance_count=expanded_instances,
        primitive_device_count=len(flattened),
    )


def parse_spice_hierarchy_sources(
    sources: Mapping[str, str],
    *,
    top_subcircuit: str,
) -> Circuit:
    expansion = expand_spice_hierarchy_sources(
        sources,
        top_subcircuit=top_subcircuit,
    )
    return parse_spice_circuit(
        expansion.flattened_spice,
        name=expansion.top_subcircuit,
    )

"""Single-level SPICE subcircuit extraction for topology parsing."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from openams.model import Circuit

from .errors import MalformedElementError, UnsupportedHierarchyError
from .spice_parser import parse_spice_circuit


@dataclass(frozen=True)
class ParsedSubcircuit:
    """One selected single-level SPICE subcircuit."""

    name: str
    ports: tuple[str, ...]
    body: str
    start_line: int
    end_line: int


def extract_spice_subcircuit(text: str, *, subcircuit: str) -> ParsedSubcircuit:
    """Extract one named, non-nested ``.subckt`` body.

    The returned body deliberately excludes the surrounding ``.subckt`` and
    ``.ends`` directives so it can be delegated to the existing flat parser.
    Nested subcircuits remain unsupported.
    """

    target = subcircuit.strip()
    if not target:
        raise ValueError("subcircuit must be non-empty")

    selected_name: str | None = None
    selected_ports: tuple[str, ...] = ()
    selected_start = 0
    body_lines: list[str] = []
    active = False
    found = False

    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("*"):
            if active:
                body_lines.append(raw)
            continue

        directive = stripped.split(None, 1)[0].lower()

        if directive == ".subckt":
            if active:
                raise UnsupportedHierarchyError(
                    f"line {line_number}: nested .subckt is unsupported"
                )

            try:
                tokens = shlex.split(stripped, comments=False, posix=True)
            except ValueError as exc:
                raise MalformedElementError(
                    f"line {line_number}: cannot tokenize .subckt declaration: {exc}"
                ) from exc

            if len(tokens) < 2:
                raise MalformedElementError(
                    f"line {line_number}: .subckt requires a name"
                )

            candidate_name = tokens[1]
            if candidate_name.lower() == target.lower():
                if found:
                    raise UnsupportedHierarchyError(
                        f"line {line_number}: duplicate subcircuit {target!r}"
                    )
                active = True
                found = True
                selected_name = candidate_name
                selected_ports = tuple(tokens[2:])
                selected_start = line_number
                body_lines = []
            continue

        if directive == ".ends":
            if not active:
                continue

            try:
                tokens = shlex.split(stripped, comments=False, posix=True)
            except ValueError as exc:
                raise MalformedElementError(
                    f"line {line_number}: cannot tokenize .ends declaration: {exc}"
                ) from exc

            if len(tokens) > 1 and tokens[1].lower() != target.lower():
                raise MalformedElementError(
                    f"line {line_number}: .ends {tokens[1]!r} does not match "
                    f".subckt {target!r}"
                )

            return ParsedSubcircuit(
                name=selected_name or target,
                ports=selected_ports,
                body="\n".join(body_lines) + ("\n" if body_lines else ""),
                start_line=selected_start,
                end_line=line_number,
            )

        if active:
            body_lines.append(raw)

    if active:
        raise MalformedElementError(
            f"subcircuit {target!r} starting at line {selected_start} has no matching .ends"
        )

    raise UnsupportedHierarchyError(
        f"subcircuit {target!r} was not found"
    )


def parse_spice_subcircuit(text: str, *, subcircuit: str) -> Circuit:
    """Parse one named, single-level SPICE subcircuit into a canonical Circuit."""

    selected = extract_spice_subcircuit(text, subcircuit=subcircuit)
    return parse_spice_circuit(selected.body, name=selected.name)

"""Flat SPICE parser producing the canonical OpenAMS circuit model."""

from __future__ import annotations

import shlex
from collections.abc import Iterable
from typing import Any

from openams.model import Circuit, Device, DeviceKind, Node

from .errors import (
    DuplicateDeviceError,
    MalformedElementError,
    UnsupportedElementError,
    UnsupportedHierarchyError,
)
from .records import ParsedDevice
from .spice_numbers import parse_spice_scalar


_IGNORED_DIRECTIVES = {
    ".ac", ".control", ".dc", ".end", ".endc", ".global", ".include",
    ".lib", ".meas", ".measure", ".model", ".nodeset", ".op", ".option",
    ".options", ".param", ".save", ".temp", ".tran",
}
_HIERARCHY_DIRECTIVES = {".subckt", ".ends"}
_MOS_HINTS = ("nfet", "pfet", "nmos", "pmos", "mos")


def _logical_lines(text: str) -> Iterable[tuple[int, str]]:
    current = ""
    start_line = 0

    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("*"):
            continue

        if stripped.startswith("+"):
            if not current:
                raise MalformedElementError(
                    f"line {line_number}: continuation has no preceding line"
                )
            current += " " + stripped[1:].strip()
            continue

        if current:
            yield start_line, current

        current = stripped
        start_line = line_number

    if current:
        yield start_line, current


def _strip_inline_comment(line: str) -> str:
    quoted = False
    quote = ""
    result: list[str] = []
    for char in line:
        if char in {"'", '"'}:
            if not quoted:
                quoted = True
                quote = char
            elif char == quote:
                quoted = False
            result.append(char)
        elif char == "$" and not quoted:
            break
        else:
            result.append(char)
    return "".join(result).strip()


def _tokens(line: str, line_number: int) -> list[str]:
    try:
        return shlex.split(line, comments=False, posix=True)
    except ValueError as exc:
        raise MalformedElementError(
            f"line {line_number}: cannot tokenize element: {exc}"
        ) from exc


def _parameters(tokens: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    positional: list[str] = []
    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            key = key.strip().lower()
            if key:
                result[key] = parse_spice_scalar(value)
        else:
            positional.append(token)
    if positional:
        result["value"] = " ".join(positional)
    return result


def _parse_mos(tokens: list[str], line_number: int) -> ParsedDevice:
    if len(tokens) < 6:
        raise MalformedElementError(
            f"line {line_number}: MOS requires name, four nodes, and model"
        )
    name, drain, gate, source, bulk, model, *tail = tokens
    return ParsedDevice(
        name=name,
        kind="mos",
        model=model,
        terminals={
            "drain": drain,
            "gate": gate,
            "source": source,
            "bulk": bulk,
        },
        parameters=_parameters(tail),
        source_line=line_number,
    )


def _parse_two_terminal(
    tokens: list[str],
    line_number: int,
    *,
    kind: str,
) -> ParsedDevice:
    if len(tokens) < 4:
        raise MalformedElementError(
            f"line {line_number}: {kind} requires name, two nodes, and value"
        )
    name, positive, negative, *tail = tokens
    return ParsedDevice(
        name=name,
        kind=kind,
        model=None,
        terminals={"positive": positive, "negative": negative},
        parameters=_parameters(tail),
        source_line=line_number,
    )


def _parse_x_mos(tokens: list[str], line_number: int) -> ParsedDevice:
    if len(tokens) < 6:
        name = tokens[0] if tokens else "<unknown>"
        raise UnsupportedHierarchyError(
            f"line {line_number}: X instance {name!r} is not recognizably MOS; "
            "hierarchical pin semantics are unavailable"
        )

    # Four nodes + one model token; remaining tokens must be parameters.
    name = tokens[0]
    drain, gate, source, bulk, model = tokens[1:6]
    tail = tokens[6:]
    if not any(hint in model.lower() for hint in _MOS_HINTS):
        raise UnsupportedHierarchyError(
            f"line {line_number}: X instance {name!r} is not recognizably MOS; "
            "hierarchical pin semantics are unavailable"
        )
    if any("=" not in token for token in tail):
        raise UnsupportedHierarchyError(
            f"line {line_number}: X instance {name!r} has more than four nodes"
        )
    return ParsedDevice(
        name=name,
        kind="mos",
        model=model,
        terminals={
            "drain": drain,
            "gate": gate,
            "source": source,
            "bulk": bulk,
        },
        parameters=_parameters(tail),
        source_line=line_number,
    )


def _parse_device(tokens: list[str], line_number: int) -> ParsedDevice:
    if not tokens or not tokens[0]:
        raise MalformedElementError(f"line {line_number}: empty element")

    prefix = tokens[0][0].upper()
    if prefix == "M":
        return _parse_mos(tokens, line_number)
    if prefix == "X":
        return _parse_x_mos(tokens, line_number)
    if prefix == "R":
        return _parse_two_terminal(tokens, line_number, kind="resistor")
    if prefix == "C":
        return _parse_two_terminal(tokens, line_number, kind="capacitor")
    if prefix == "V":
        return _parse_two_terminal(tokens, line_number, kind="voltage_source")
    if prefix == "I":
        return _parse_two_terminal(tokens, line_number, kind="current_source")
    raise UnsupportedElementError(
        f"line {line_number}: unsupported element prefix {prefix!r}"
    )


def _device_kind(value: str) -> DeviceKind:
    """Resolve a parser kind into the canonical model enum.

    Matching both enum values and enum member names keeps this adapter coupled
    to the public semantic vocabulary rather than to one enum spelling style.
    """

    normalized = value.strip().lower()

    for candidate in DeviceKind:
        candidate_value = str(candidate.value).strip().lower()
        candidate_name = candidate.name.strip().lower()

        if normalized in {candidate_value, candidate_name}:
            return candidate

    raise UnsupportedElementError(
        f"topology parser produced unsupported device kind {value!r}"
    )


def _model_device(parsed: ParsedDevice) -> Device:
    return Device(
        name=parsed.name,
        kind=_device_kind(parsed.kind),
        model=parsed.model,
        terminals=parsed.terminals,
        parameters=parsed.parameters,
    )


def parse_spice_circuit(text: str, *, name: str = "circuit") -> Circuit:
    """Parse a flat SPICE netlist into an immutable canonical Circuit."""

    parsed_devices: dict[str, ParsedDevice] = {}
    node_names: set[str] = set()

    for line_number, logical in _logical_lines(text):
        line = _strip_inline_comment(logical)
        if not line:
            continue

        if line.startswith("."):
            directive = line.split(None, 1)[0].lower()
            if directive in _HIERARCHY_DIRECTIVES:
                raise UnsupportedHierarchyError(
                    f"line {line_number}: hierarchy directive {directive!r} "
                    "is outside the flat topology subset"
                )
            if directive in _IGNORED_DIRECTIVES:
                continue
            # Unknown directives do not define connectivity and are ignored.
            continue

        tokens = _tokens(line, line_number)
        parsed = _parse_device(tokens, line_number)
        key = parsed.name.lower()
        if key in parsed_devices:
            first = parsed_devices[key]
            raise DuplicateDeviceError(
                f"line {line_number}: duplicate device {parsed.name!r}; "
                f"first declared on line {first.source_line}"
            )
        parsed_devices[key] = parsed
        node_names.update(parsed.terminals.values())

    nodes = {node_name: Node(name=node_name) for node_name in sorted(node_names)}
    devices = {
        parsed.name: _model_device(parsed)
        for parsed in parsed_devices.values()
    }

    return Circuit(name=name, nodes=nodes, devices=devices)

"""Filesystem adapter for loading recursive SPICE source trees.

This module performs only representation and filesystem work. It intentionally
does not import topology or construct canonical circuit objects.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .errors import InputError


_INCLUDE_RE = re.compile(r"^\s*\.include\s+(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class LoadedSpiceHierarchy:
    """A recursively loaded SPICE source tree."""

    root_path: str
    sources: Mapping[str, str]
    source_paths: tuple[str, ...]


def _logical_lines(text: str):
    current = ""
    start = 0

    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()

        if not stripped or stripped.startswith("*"):
            continue

        if stripped.startswith("+"):
            if not current:
                raise InputError(
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


def _included_source_tokens(text: str) -> tuple[str, ...]:
    result: list[str] = []

    for _, line in _logical_lines(text):
        match = _INCLUDE_RE.match(line)
        if not match:
            continue

        try:
            tokens = shlex.split(
                match.group(1),
                comments=False,
                posix=True,
            )
        except ValueError as exc:
            raise InputError(
                f"invalid .include declaration: {exc}"
            ) from exc

        if not tokens:
            raise InputError("empty .include declaration")

        result.append(tokens[0])

    return tuple(result)


def _resolve_include(
    requested: str,
    *,
    parent: Path,
    search_roots: tuple[Path, ...],
) -> Path:
    token = Path(requested).expanduser()
    candidates: list[Path] = []

    if token.is_absolute():
        candidates.append(token)
    else:
        candidates.append(parent.parent / token)

    candidates.append(parent.parent / token.name)
    candidates.extend(root / token.name for root in search_roots)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise InputError(
        f"{parent}: included file {requested!r} could not be resolved"
    )


def load_spice_hierarchy(
    root_path: str | Path,
    *,
    include_search_roots: Iterable[str | Path] = (),
) -> LoadedSpiceHierarchy:
    """Load a root SPICE file and all recursively referenced include files."""

    root = Path(root_path).expanduser().resolve()
    roots = tuple(
        Path(item).expanduser().resolve()
        for item in include_search_roots
    )

    loaded_by_path: dict[Path, str] = {}
    ordered_paths: list[Path] = []

    def visit(path: Path) -> None:
        resolved = path.resolve()

        if resolved in loaded_by_path:
            return

        if not resolved.is_file():
            raise InputError(
                f"SPICE source does not exist or is not a file: {resolved}"
            )

        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise InputError(
                f"cannot read SPICE source: {resolved}"
            ) from exc

        loaded_by_path[resolved] = text
        ordered_paths.append(resolved)

        for requested in _included_source_tokens(text):
            visit(
                _resolve_include(
                    requested,
                    parent=resolved,
                    search_roots=roots,
                )
            )

    visit(root)

    sources = {
        str(path): loaded_by_path[path]
        for path in ordered_paths
    }

    return LoadedSpiceHierarchy(
        root_path=str(root),
        sources=sources,
        source_paths=tuple(str(path) for path in ordered_paths),
    )

"""Raw CSV loading for characterization data.

This module performs representation and filesystem work only. It does not
construct technology-domain objects.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .errors import InputError


@dataclass(frozen=True, slots=True)
class LoadedCharacterizationCsv:
    source_path: str
    fieldnames: tuple[str, ...]
    rows: tuple[Mapping[str, str], ...]


def load_characterization_csv(
    path: str | Path,
) -> LoadedCharacterizationCsv:
    source = Path(path).expanduser()
    if not source.is_file():
        raise InputError(
            f"characterization CSV does not exist or is not a file: {source}"
        )

    try:
        handle = source.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise InputError(f"cannot read characterization CSV: {source}") from exc

    with handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        if not fieldnames:
            raise InputError("characterization CSV has no header")

        rows = tuple(
            MappingProxyType(
                {
                    str(key): "" if value is None else str(value)
                    for key, value in row.items()
                }
            )
            for row in reader
        )

    if not rows:
        raise InputError("characterization CSV contains no data rows")

    return LoadedCharacterizationCsv(
        source_path=str(source),
        fieldnames=fieldnames,
        rows=rows,
    )

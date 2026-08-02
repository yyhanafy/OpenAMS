"""Adapter from raw characterization CSV data to technology-domain objects."""

from __future__ import annotations

from math import isfinite
from typing import Mapping

from openams.io import LoadedCharacterizationCsv, load_characterization_csv
from openams.io.errors import InputError
from openams.technology import (
    CharacterizationPoint,
    DeviceKind,
    DeviceModel,
    DeviceOperatingPoint,
    DevicePolarity,
    OperatingCondition,
    OperatingRegion,
    SignConvention,
    TechnologyCapabilities,
    TechnologyIdentity,
    TechnologyQuantity,
)
from openams.technology.table import CharacterizationTable


_REQUIRED_COLUMNS = {
    "polarity",
    "model",
    "corner",
    "temperature_c",
    "length_um",
    "width_um",
    "vgs_abs_v",
    "vds_abs_v",
    "vbs_abs_v",
}

_QUANTITY_COLUMNS = {
    "id_abs_a": TechnologyQuantity.ID,
    "gm_s": TechnologyQuantity.GM,
    "gds_s": TechnologyQuantity.GDS,
    "vth_abs_v": TechnologyQuantity.VTH,
    "vdsat_abs_v": TechnologyQuantity.VDSAT,
}

_TRUE_VALUES = {"1", "true", "yes", "y"}
_FALSE_VALUES = {"0", "false", "no", "n"}


def _required_text(row: Mapping[str, str], key: str, line: int) -> str:
    value = str(row.get(key, "")).strip()
    if not value:
        raise InputError(f"line {line}: missing required field {key!r}")
    return value


def _required_float(row: Mapping[str, str], key: str, line: int) -> float:
    text = _required_text(row, key, line)
    try:
        return float(text)
    except ValueError as exc:
        raise InputError(f"line {line}: field {key!r} must be numeric") from exc


def _optional_float(
    row: Mapping[str, str],
    key: str,
    line: int,
) -> float | None:
    text = str(row.get(key, "")).strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise InputError(f"line {line}: field {key!r} must be numeric") from exc

    # Dense characterization files may contain NaN or infinity for optional
    # metrics that a simulator could not extract at a particular point.
    # Those quantities are omitted from that point instead of invalidating the
    # entire table. Required coordinate fields remain strict and finite.
    if not isfinite(value):
        return None

    return value


def _polarity(value: str, line: int) -> DevicePolarity:
    try:
        return DevicePolarity(value.strip().lower())
    except ValueError as exc:
        raise InputError(f"line {line}: unsupported polarity {value!r}") from exc


def _region(row: Mapping[str, str], line: int) -> OperatingRegion:
    text = str(row.get("saturated", "")).strip().lower()
    if not text:
        return OperatingRegion.UNKNOWN
    if text in _TRUE_VALUES:
        return OperatingRegion.SATURATION
    if text in _FALSE_VALUES:
        return OperatingRegion.LINEAR
    raise InputError(
        f"line {line}: field 'saturated' must be boolean-like"
    )


def build_characterization_table(
    loaded: LoadedCharacterizationCsv,
    *,
    technology_name: str | None = None,
) -> CharacterizationTable:
    missing = sorted(_REQUIRED_COLUMNS - set(loaded.fieldnames))
    if missing:
        raise InputError(
            f"characterization CSV is missing required columns: {missing!r}"
        )

    available_quantities = {
        column: quantity
        for column, quantity in _QUANTITY_COLUMNS.items()
        if column in loaded.fieldnames
    }
    if not available_quantities:
        raise InputError(
            "characterization CSV contains no supported quantity columns"
        )

    models: dict[tuple[str, DevicePolarity], DeviceModel] = {}
    points: list[CharacterizationPoint] = []
    polarities: set[DevicePolarity] = set()
    quantities: set[TechnologyQuantity] = set()
    corners: set[str] = set()
    temperatures: set[float] = set()

    for line, row in enumerate(loaded.rows, start=2):
        polarity = _polarity(_required_text(row, "polarity", line), line)
        model_name = _required_text(row, "model", line)
        model_key = (model_name, polarity)

        model = models.get(model_key)
        if model is None:
            model = DeviceModel(
                name=model_name,
                polarity=polarity,
                kind=DeviceKind.MOS,
            )
            models[model_key] = model

        corner = _required_text(row, "corner", line)
        temperature_c = _required_float(row, "temperature_c", line)

        values: dict[TechnologyQuantity, float] = {}
        for column, quantity in available_quantities.items():
            value = _optional_float(row, column, line)
            if value is not None:
                values[quantity] = value
                quantities.add(quantity)

        if not values:
            raise InputError(
                f"line {line}: characterization point has no values"
            )

        point = CharacterizationPoint(
            operating_point=DeviceOperatingPoint(
                model=model,
                condition=OperatingCondition(
                    corner=corner,
                    temperature_c=temperature_c,
                ),
                length_m=_required_float(row, "length_um", line) * 1e-6,
                width_m=_required_float(row, "width_um", line) * 1e-6,
                vgs_v=_required_float(row, "vgs_abs_v", line),
                vds_v=_required_float(row, "vds_abs_v", line),
                vbs_v=_required_float(row, "vbs_abs_v", line),
            ),
            values=values,
            region=_region(row, line),
            source=loaded.source_path,
            metadata={"csv_line": line},
        )
        points.append(point)
        polarities.add(polarity)
        corners.add(corner)
        temperatures.add(temperature_c)

    return CharacterizationTable(
        identity=TechnologyIdentity(
            name=technology_name or "characterization_table",
            metadata={
                "source_path": loaded.source_path,
                "corners": tuple(sorted(corners)),
                "temperatures_c": tuple(sorted(temperatures)),
                "model_count": len(models),
            },
        ),
        capabilities=TechnologyCapabilities(
            device_kinds={DeviceKind.MOS},
            polarities=polarities,
            quantities=quantities,
            sign_convention=SignConvention.ABSOLUTE_MAGNITUDE,
            saturation_classification="saturated" in loaded.fieldnames,
            interpolation=False,
            inverse_queries=False,
            derivatives=(
                TechnologyQuantity.GM in quantities
                or TechnologyQuantity.GDS in quantities
            ),
            metadata={
                "source_format": "characterization_csv",
                "quantity_columns": tuple(available_quantities),
            },
        ),
        points=tuple(points),
        metadata={
            "source_path": loaded.source_path,
            "row_count": len(points),
        },
    )


def load_characterization_table_csv(
    path,
    *,
    technology_name: str | None = None,
) -> CharacterizationTable:
    return build_characterization_table(
        load_characterization_csv(path),
        technology_name=technology_name,
    )

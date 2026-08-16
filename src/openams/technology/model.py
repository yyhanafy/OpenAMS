"""Immutable technology contract records."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from ._immutable import (
    freeze_mapping,
    freeze_numeric_mapping,
    optional_name,
    require_finite,
    require_name,
    require_positive,
)
from .errors import TechnologyValidationError


class DeviceKind(str, Enum):
    MOS = "mos"


class DevicePolarity(str, Enum):
    NMOS = "nmos"
    PMOS = "pmos"


class OperatingRegion(str, Enum):
    UNKNOWN = "unknown"
    CUTOFF = "cutoff"
    LINEAR = "linear"
    SATURATION = "saturation"
    SUBTHRESHOLD = "subthreshold"


class SignConvention(str, Enum):
    SIGNED_TERMINAL_CURRENT = "signed_terminal_current"
    ABSOLUTE_MAGNITUDE = "absolute_magnitude"


class TechnologyQuantity(str, Enum):
    ID = "id"
    GM = "gm"
    GDS = "gds"
    GMB = "gmb"
    VTH = "vth"
    VDSAT = "vdsat"
    CAP_GS = "cap_gs"
    CAP_GD = "cap_gd"
    CAP_GB = "cap_gb"
    CAP_DB = "cap_db"
    CAP_SB = "cap_sb"
    NOISE_DENSITY = "noise_density"


@dataclass(frozen=True, slots=True, kw_only=True)
class TechnologyIdentity:
    name: str
    foundry: str | None = None
    pdk_version: str | None = None
    model_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "name", require_name(self.name, "technology name")
        )
        object.__setattr__(
            self, "foundry", optional_name(self.foundry, "foundry")
        )
        object.__setattr__(
            self,
            "pdk_version",
            optional_name(self.pdk_version, "PDK version"),
        )
        object.__setattr__(
            self,
            "model_version",
            optional_name(self.model_version, "model version"),
        )
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatingCondition:
    corner: str
    temperature_c: float
    supply_voltage_v: float | None = None
    body_bias_v: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "corner", require_name(self.corner, "process corner")
        )
        object.__setattr__(
            self,
            "temperature_c",
            require_finite(self.temperature_c, "temperature_c"),
        )
        if self.supply_voltage_v is not None:
            object.__setattr__(
                self,
                "supply_voltage_v",
                require_finite(self.supply_voltage_v, "supply_voltage_v"),
            )
        if self.body_bias_v is not None:
            object.__setattr__(
                self,
                "body_bias_v",
                require_finite(self.body_bias_v, "body_bias_v"),
            )
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceModel:
    name: str
    polarity: DevicePolarity
    kind: DeviceKind = DeviceKind.MOS
    voltage_class: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_name(self.name, "device model name"))
        if not isinstance(self.polarity, DevicePolarity):
            raise TypeError("polarity must be a DevicePolarity")
        if not isinstance(self.kind, DeviceKind):
            raise TypeError("kind must be a DeviceKind")
        object.__setattr__(
            self,
            "voltage_class",
            optional_name(self.voltage_class, "voltage class"),
        )
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceOperatingPoint:
    model: DeviceModel
    condition: OperatingCondition
    length_m: float
    width_m: float
    vgs_v: float
    vds_v: float
    vbs_v: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.model, DeviceModel):
            raise TypeError("model must be a DeviceModel")
        if not isinstance(self.condition, OperatingCondition):
            raise TypeError("condition must be an OperatingCondition")
        object.__setattr__(
            self, "length_m", require_positive(self.length_m, "length_m")
        )
        object.__setattr__(
            self, "width_m", require_positive(self.width_m, "width_m")
        )
        object.__setattr__(self, "vgs_v", require_finite(self.vgs_v, "vgs_v"))
        object.__setattr__(self, "vds_v", require_finite(self.vds_v, "vds_v"))
        object.__setattr__(self, "vbs_v", require_finite(self.vbs_v, "vbs_v"))


@dataclass(frozen=True, slots=True, kw_only=True)
class TechnologyCapabilities:
    device_kinds: frozenset[DeviceKind]
    polarities: frozenset[DevicePolarity]
    quantities: frozenset[TechnologyQuantity]
    sign_convention: SignConvention
    saturation_classification: bool = False
    interpolation: bool = False
    inverse_queries: bool = False
    derivatives: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kinds = frozenset(self.device_kinds)
        polarities = frozenset(self.polarities)
        quantities = frozenset(self.quantities)
        if not kinds:
            raise TechnologyValidationError(
                "technology capabilities require a device kind"
            )
        if not polarities:
            raise TechnologyValidationError(
                "technology capabilities require a polarity"
            )
        if not quantities:
            raise TechnologyValidationError(
                "technology capabilities require a quantity"
            )
        if not all(isinstance(value, DeviceKind) for value in kinds):
            raise TypeError("device_kinds must contain DeviceKind values")
        if not all(isinstance(value, DevicePolarity) for value in polarities):
            raise TypeError("polarities must contain DevicePolarity values")
        if not all(isinstance(value, TechnologyQuantity) for value in quantities):
            raise TypeError("quantities must contain TechnologyQuantity values")
        if not isinstance(self.sign_convention, SignConvention):
            raise TypeError("sign_convention must be a SignConvention")
        for field_name in (
            "saturation_classification",
            "interpolation",
            "inverse_queries",
            "derivatives",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be boolean")

        object.__setattr__(self, "device_kinds", kinds)
        object.__setattr__(self, "polarities", polarities)
        object.__setattr__(self, "quantities", quantities)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class TechnologyLookupRequest:
    operating_point: DeviceOperatingPoint
    quantities: frozenset[TechnologyQuantity]
    require_saturation: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.operating_point, DeviceOperatingPoint):
            raise TypeError("operating_point must be a DeviceOperatingPoint")
        quantities = frozenset(self.quantities)
        if not quantities:
            raise TechnologyValidationError(
                "lookup request requires at least one quantity"
            )
        if not all(isinstance(value, TechnologyQuantity) for value in quantities):
            raise TypeError("quantities must contain TechnologyQuantity values")
        if not isinstance(self.require_saturation, bool):
            raise TypeError("require_saturation must be boolean")
        object.__setattr__(self, "quantities", quantities)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class TechnologyLookupResult:
    request: TechnologyLookupRequest
    values: Mapping[TechnologyQuantity, float]
    region: OperatingRegion
    backend: TechnologyIdentity
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request, TechnologyLookupRequest):
            raise TypeError("request must be a TechnologyLookupRequest")
        if not isinstance(self.region, OperatingRegion):
            raise TypeError("region must be an OperatingRegion")
        if not isinstance(self.backend, TechnologyIdentity):
            raise TypeError("backend must be a TechnologyIdentity")
        object.__setattr__(
            self,
            "values",
            freeze_numeric_mapping(
                self.values,
                field_name="values",
                key_type=TechnologyQuantity,
            ),
        )
        object.__setattr__(self, "diagnostics", freeze_mapping(self.diagnostics))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True, kw_only=True)
class CharacterizationPoint:
    operating_point: DeviceOperatingPoint
    values: Mapping[TechnologyQuantity, float]
    region: OperatingRegion = OperatingRegion.UNKNOWN
    source: str = "unspecified"
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.operating_point, DeviceOperatingPoint):
            raise TypeError("operating_point must be a DeviceOperatingPoint")
        if not isinstance(self.region, OperatingRegion):
            raise TypeError("region must be an OperatingRegion")
        object.__setattr__(self, "source", require_name(self.source, "source"))
        values = freeze_numeric_mapping(
            self.values,
            field_name="values",
            key_type=TechnologyQuantity,
        )
        if not values:
            raise TechnologyValidationError(
                "characterization point requires at least one value"
            )
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "diagnostics", freeze_mapping(self.diagnostics))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

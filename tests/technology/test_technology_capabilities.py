from openams.technology import (
    DeviceKind,
    DeviceModel,
    DeviceOperatingPoint,
    DevicePolarity,
    OperatingCondition,
    SignConvention,
    TechnologyCapabilities,
    TechnologyLookupRequest,
    TechnologyQuantity,
    missing_capabilities,
    supports_request,
)


def make_request(*, require_saturation: bool = False) -> TechnologyLookupRequest:
    return TechnologyLookupRequest(
        operating_point=DeviceOperatingPoint(
            model=DeviceModel(
                name="pfet",
                polarity=DevicePolarity.PMOS,
            ),
            condition=OperatingCondition(corner="tt", temperature_c=27),
            length_m=0.5e-6,
            width_m=4e-6,
            vgs_v=0.8,
            vds_v=0.8,
        ),
        quantities={TechnologyQuantity.ID, TechnologyQuantity.GM},
        require_saturation=require_saturation,
    )


def test_request_capability_inspection() -> None:
    capabilities = TechnologyCapabilities(
        device_kinds={DeviceKind.MOS},
        polarities={DevicePolarity.PMOS},
        quantities={TechnologyQuantity.ID, TechnologyQuantity.GM},
        sign_convention=SignConvention.ABSOLUTE_MAGNITUDE,
        saturation_classification=True,
    )
    request = make_request(require_saturation=True)

    assert missing_capabilities(capabilities, request) == frozenset()
    assert supports_request(capabilities, request)


def test_missing_capabilities_are_explicit() -> None:
    capabilities = TechnologyCapabilities(
        device_kinds={DeviceKind.MOS},
        polarities={DevicePolarity.NMOS},
        quantities={TechnologyQuantity.ID},
        sign_convention=SignConvention.SIGNED_TERMINAL_CURRENT,
    )
    missing = missing_capabilities(
        capabilities,
        make_request(require_saturation=True),
    )

    assert missing == frozenset(
        {
            "polarity:pmos",
            "quantity:gm",
            "saturation_classification",
        }
    )

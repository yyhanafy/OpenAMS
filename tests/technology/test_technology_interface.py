from openams.technology import (
    DeviceKind,
    DeviceModel,
    DeviceOperatingPoint,
    DevicePolarity,
    OperatingCondition,
    OperatingRegion,
    SignConvention,
    TechnologyBackend,
    TechnologyCapabilities,
    TechnologyIdentity,
    TechnologyLookupRequest,
    TechnologyLookupResult,
    TechnologyQuantity,
)


class FakeBackend:
    @property
    def identity(self) -> TechnologyIdentity:
        return TechnologyIdentity(name="fake")

    @property
    def capabilities(self) -> TechnologyCapabilities:
        return TechnologyCapabilities(
            device_kinds={DeviceKind.MOS},
            polarities={DevicePolarity.NMOS},
            quantities={TechnologyQuantity.ID},
            sign_convention=SignConvention.ABSOLUTE_MAGNITUDE,
        )

    def lookup(
        self,
        request: TechnologyLookupRequest,
    ) -> TechnologyLookupResult:
        return TechnologyLookupResult(
            request=request,
            values={TechnologyQuantity.ID: 1e-6},
            region=OperatingRegion.UNKNOWN,
            backend=self.identity,
        )


def test_backend_protocol_is_runtime_checkable() -> None:
    backend = FakeBackend()
    assert isinstance(backend, TechnologyBackend)

    request = TechnologyLookupRequest(
        operating_point=DeviceOperatingPoint(
            model=DeviceModel(name="nfet", polarity=DevicePolarity.NMOS),
            condition=OperatingCondition(corner="tt", temperature_c=27),
            length_m=0.5e-6,
            width_m=1e-6,
            vgs_v=0.8,
            vds_v=0.8,
        ),
        quantities={TechnologyQuantity.ID},
    )
    assert backend.lookup(request).values[TechnologyQuantity.ID] == 1e-6

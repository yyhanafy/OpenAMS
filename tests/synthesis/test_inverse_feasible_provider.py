from __future__ import annotations

import csv
from pathlib import Path

from openams.synthesis.generic_complete_step5 import DeviceRequest
from openams.synthesis.inverse_feasible_provider import InverseFeasibleDatasetProvider


def test_inverse_provider_reduces_vds_rows_to_w_vgs_tuple(tmp_path: Path) -> None:
    path = tmp_path / "technology.csv"
    fields = [
        "polarity", "model", "length_um", "width_um", "vgs_v", "vds_v",
        "vbs_v", "id_abs_a", "vdsat_abs_v", "saturated", "gm", "gds", "vth",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for vds in (0.2, 0.4, 0.8):
            writer.writerow(
                {
                    "polarity": "nmos", "model": "nmos", "length_um": 0.5,
                    "width_um": 10.0, "vgs_v": 0.7, "vds_v": vds, "vbs_v": 0.0,
                    "id_abs_a": 50e-6, "vdsat_abs_v": 0.1, "saturated": True,
                    "gm": 1e-3, "gds": 1e-5, "vth": 0.55,
                }
            )
    provider = InverseFeasibleDatasetProvider(path, saturation_margin_v=0.05)
    request = DeviceRequest(
        device="M1", model="nmos", polarity="nmos", length_um=0.5,
        target_current_a=50e-6, fixed_width_um=10.0,
        known_vgs_v=None, known_vds_v=None, known_vbs_v=0.0,
        require_saturation=True,
    )
    candidates = provider.candidates(
        request,
        current_relative_tolerance=0.1,
        current_absolute_tolerance_a=1e-6,
        voltage_tolerance_v=0.025,
        width_policy={
            "total_min_um": 0.42, "total_max_um": 100.0,
            "finger_min_um": 0.42, "finger_max_um": 100.0,
            "nf_min": 1, "nf_max": 8,
        },
        limit=16,
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.width_um == 10.0
    assert candidate.vgs_v == 0.7
    assert candidate.provenance["supporting_row_count"] == 3
    assert candidate.provenance["minimum_saturated_vds_v"] == 0.2
    assert candidate.provenance["maximum_characterized_vds_v"] == 0.8


class _FakeFallback:
    name = "fake_mlp"

    def __init__(self) -> None:
        self.query_count = 0

    def candidates(self, request, *, width_policy, **kwargs):
        from openams.synthesis.generic_complete_step5 import DeviceRealization, _minimum_nf
        self.query_count += 1
        width = float(request.fixed_width_um or 7.0)
        nf = _minimum_nf(width, width_policy)
        assert nf is not None
        return [DeviceRealization(
            width_um=width,
            nf=nf,
            finger_width_um=width / nf,
            predicted_current_a=request.target_current_a,
            vgs_v=float(request.known_vgs_v or 0.75),
            vds_v=float(request.known_vds_v or 0.3),
            vbs_v=float(request.known_vbs_v or 0.0),
            vdsat_v=0.12,
            saturated=True,
            provenance={"provider": self.name},
        )]


def test_hybrid_provider_falls_back_and_reuses_cache(tmp_path: Path) -> None:
    from openams.synthesis.inverse_feasible_provider import HybridInverseFeasibleProvider

    path = tmp_path / "technology.csv"
    fields = [
        "polarity", "model", "length_um", "width_um", "vgs_v", "vds_v",
        "vbs_v", "id_abs_a", "vdsat_abs_v", "saturated",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "polarity": "nmos", "model": "nmos", "length_um": 0.5,
            "width_um": 10.0, "vgs_v": 0.7, "vds_v": 0.3,
            "vbs_v": 0.0, "id_abs_a": 50e-6,
            "vdsat_abs_v": 0.1, "saturated": True,
        })

    fallback = _FakeFallback()
    cache = tmp_path / "adaptive.csv"
    provider = HybridInverseFeasibleProvider(
        path, fallback_provider=fallback, adaptive_cache_path=cache
    )
    request = DeviceRequest(
        device="M1", model="nmos", polarity="nmos", length_um=0.5,
        target_current_a=50e-6, fixed_width_um=11.25,
        known_vgs_v=None, known_vds_v=None, known_vbs_v=0.0,
        require_saturation=True,
    )
    kwargs = dict(
        current_relative_tolerance=0.1,
        current_absolute_tolerance_a=1e-6,
        voltage_tolerance_v=0.025,
        width_policy={
            "total_min_um": 0.42, "total_max_um": 100.0,
            "finger_min_um": 0.42, "finger_max_um": 100.0,
            "nf_min": 1, "nf_max": 8,
        },
        limit=16,
    )
    first = provider.candidates(request, **kwargs)
    second = provider.candidates(request, **kwargs)

    assert len(first) == 1
    assert first[0].width_um == 11.25
    assert first[0].provenance["realization_source"] == "direct_mlp_fallback"
    assert fallback.query_count == 1
    assert provider.fallback_request_count == 1
    assert provider.cache_hit_count == 1
    assert cache.is_file()
    assert second[0].width_um == 11.25

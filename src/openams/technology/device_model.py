"""Common MOS inverse-query backends for table, MLP, and comparison modes."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .mos_table_lookup import MosGenericLookupRequest, MosTableResolver
from .ml_surrogate.predictor import MosMlpBundle


@dataclass(frozen=True)
class MosDeviceSolveResult:
    solve_for: str
    value: float
    target_current_a: float
    lower_value: float
    upper_value: float
    lower_current_a: float
    upper_current_a: float
    source_row_count: int
    characterized_point_count: int
    method: str
    interpolation_dimensions: tuple[str, ...]
    backend: str
    comparison: dict[str, Any] | None = None


class MosDeviceResolver(Protocol):
    def resolve(self, request: MosGenericLookupRequest) -> MosDeviceSolveResult: ...


class MosTableDeviceResolver:
    def __init__(self, resolver: MosTableResolver):
        self.resolver = resolver

    @classmethod
    def from_csv(cls, path: str | Path) -> "MosTableDeviceResolver":
        return cls(MosTableResolver.from_csv(path))

    def resolve(self, request: MosGenericLookupRequest) -> MosDeviceSolveResult:
        result = self.resolver.resolve(request)
        return MosDeviceSolveResult(**asdict(result), backend="table")


class MosMlpDeviceResolver:
    def __init__(self, bundle: MosMlpBundle):
        self.bundle = bundle

    @classmethod
    def from_checkpoints(cls, checkpoints: dict[str, str | Path]) -> "MosMlpDeviceResolver":
        return cls(MosMlpBundle.load(checkpoints))

    def resolve(self, request: MosGenericLookupRequest) -> MosDeviceSolveResult:
        polarity = request.polarity.lower()
        common = dict(
            polarity=polarity,
            target_current_a=abs(float(request.target_current_a)),
            length_um=float(request.length_um),
            vds_abs_v=abs(float(request.vds_v)),
            vbs_abs_v=abs(float(request.vbs_v)),
            require_saturation=bool(request.require_saturation),
        )
        if request.solve_for.lower() == "width":
            if request.vgs_v is None:
                raise ValueError("solve_for=width requires vgs_v")
            solved = self.bundle.solve_width(
                **common,
                vgs_abs_v=abs(float(request.vgs_v)),
                minimum_width_um=request.minimum_width_um,
                maximum_width_um=request.maximum_width_um,
            )
            dims = ("length_um", "vgs_v", "vds_v", "vbs_v")
        elif request.solve_for.lower() == "vgs":
            if request.width_um is None:
                raise ValueError("solve_for=vgs requires width_um")
            solved = self.bundle.solve_vgs(
                **common,
                width_um=float(request.width_um),
                minimum_vgs_abs_v=request.minimum_vgs_v,
                maximum_vgs_abs_v=request.maximum_vgs_v,
            )
            dims = ("length_um", "width_um", "vds_v", "vbs_v")
        else:
            raise ValueError(f"unsupported solve_for={request.solve_for!r}")
        return MosDeviceSolveResult(
            solve_for=solved.solve_for,
            value=solved.value,
            target_current_a=solved.target_current_a,
            lower_value=solved.bracket[0],
            upper_value=solved.bracket[1],
            lower_current_a=float("nan"),
            upper_current_a=float("nan"),
            source_row_count=0,
            characterized_point_count=129,
            method=solved.method,
            interpolation_dimensions=dims,
            backend="mlp",
        )


class MosCompareDeviceResolver:
    """Evaluate both backends and return the selected backend's value."""
    def __init__(self, table: MosTableDeviceResolver, mlp: MosMlpDeviceResolver,
                 result_backend: str = "table"):
        if result_backend not in {"table", "mlp"}:
            raise ValueError("result_backend must be 'table' or 'mlp'")
        self.table, self.mlp, self.result_backend = table, mlp, result_backend

    def resolve(self, request: MosGenericLookupRequest) -> MosDeviceSolveResult:
        table_result = self.table.resolve(request)
        mlp_result = self.mlp.resolve(request)
        selected = table_result if self.result_backend == "table" else mlp_result
        delta = mlp_result.value - table_result.value
        rel = abs(delta) / max(abs(table_result.value), 1e-30)
        comparison = {
            "selected_backend": self.result_backend,
            "table": asdict(table_result),
            "mlp": asdict(mlp_result),
            "delta_value": delta,
            "relative_delta": rel,
        }
        return MosDeviceSolveResult(
            **{k: v for k, v in asdict(selected).items() if k != "comparison"},
            comparison=comparison,
        )


def build_device_resolver(config: dict[str, Any]) -> MosDeviceResolver:
    provider = str(config.get("provider", "mos_inverse_table")).lower()
    if provider == "mos_inverse_table":
        return MosTableDeviceResolver.from_csv(config["path"])
    checkpoints = {k: Path(v) for k, v in config.get("checkpoints", {}).items()}
    if set(checkpoints) != {"nmos", "pmos"}:
        raise ValueError("MLP providers require checkpoints.nmos and checkpoints.pmos")
    mlp = MosMlpDeviceResolver.from_checkpoints(checkpoints)
    if provider == "mos_mlp":
        return mlp
    if provider == "mos_compare":
        table = MosTableDeviceResolver.from_csv(config["path"])
        return MosCompareDeviceResolver(table, mlp, str(config.get("result_backend", "table")))
    raise ValueError(f"unsupported MOS provider {provider!r}")

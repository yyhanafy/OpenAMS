"""Hierarchical synthesis workflow over explicit device and stage regions."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .compiler import (
    CircuitConstraintCompiler,
    CompiledIntersection,
    ConstraintCompilationDiagnostic,
    RegionBinding,
)
from .errors import InvalidRegionError, SynthesisError
from .indexed import PlannedIntersectionPolicy
from .model import CircuitRegion, RegionInput


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class CanonicalConstraintRecord:
    """Portable constraint record accepted by the canonical compiler."""

    name: str
    expression: str
    kind: str = "equality"
    source: str = "design_intent"

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.expression.strip():
            raise SynthesisError("constraint records require non-empty name and expression")


@dataclass(frozen=True)
class SynthesisStage:
    """One named intersection over previously available region bindings."""

    name: str
    input_names: tuple[str, ...]
    constraints: tuple[Any, ...]
    strict: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidRegionError("synthesis stage name must be non-empty")
        names = tuple(self.input_names)
        if not names:
            raise InvalidRegionError("synthesis stage requires at least one input")
        if len(set(names)) != len(names):
            raise InvalidRegionError("synthesis stage input names must be unique")
        object.__setattr__(self, "input_names", names)
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True)
class StageResult:
    stage: SynthesisStage
    compiled: CompiledIntersection
    region: CircuitRegion
    output_binding: RegionBinding

    @property
    def retained_count(self) -> int:
        return self.region.retained_count


@dataclass(frozen=True)
class SynthesisWorkflowResult:
    initial_binding_names: tuple[str, ...]
    stages: tuple[StageResult, ...]
    bindings: Mapping[str, RegionBinding]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))

    @property
    def final(self) -> StageResult:
        if not self.stages:
            raise SynthesisError("workflow has no executed stages")
        return self.stages[-1]

    def stage(self, name: str) -> StageResult:
        for result in self.stages:
            if result.stage.name == name:
                return result
        raise KeyError(name)


class HierarchicalSynthesisWorkflow:
    """Compile and execute a dependency-ordered sequence of region intersections.

    Each completed stage is converted into a new ``RegionBinding``.  Its rows
    retain the original namespaced fields, and its canonical field map is
    carried forward automatically.  This lets later stages intersect compact
    stage regions instead of re-enumerating all underlying device tables.
    """

    def __init__(
        self,
        *,
        compiler: CircuitConstraintCompiler | None = None,
        policy: PlannedIntersectionPolicy | None = None,
        reject_empty_stage: bool = False,
    ) -> None:
        self._compiler = compiler or CircuitConstraintCompiler()
        self._policy = policy
        self._reject_empty_stage = reject_empty_stage

    def run(
        self,
        initial_bindings: Sequence[RegionBinding],
        stages: Iterable[SynthesisStage],
    ) -> SynthesisWorkflowResult:
        catalog: dict[str, RegionBinding] = {}
        for binding in initial_bindings:
            if binding.region_name in catalog:
                raise InvalidRegionError(f"duplicate initial binding {binding.region_name!r}")
            catalog[binding.region_name] = binding

        initial_names = tuple(catalog)
        results: list[StageResult] = []
        for stage in stages:
            if stage.name in catalog:
                raise InvalidRegionError(f"stage output name {stage.name!r} already exists")
            missing = tuple(name for name in stage.input_names if name not in catalog)
            if missing:
                raise InvalidRegionError(
                    f"stage {stage.name!r} references unavailable inputs: {', '.join(missing)}"
                )
            selected = tuple(catalog[name] for name in stage.input_names)
            compiled = self._compiler.compile(stage.constraints, selected, strict=stage.strict)
            region = compiled.build(policy=self._policy)
            if self._reject_empty_stage and region.is_empty:
                raise SynthesisError(f"stage {stage.name!r} produced an empty circuit region")

            output_rows = region.dictionaries()
            output_region = RegionInput(
                stage.name,
                output_rows,
                metadata={
                    "source_kind": "synthesis_stage",
                    "stage_name": stage.name,
                    "stage_inputs": stage.input_names,
                    "retained_count": region.retained_count,
                    "intersection_method": region.metadata.get("intersection_method", "unknown"),
                    **dict(stage.metadata),
                },
            )
            # Circuit rows already contain the synthesis field names emitted by
            # the compiler (for example M1.id).  These become local fields of
            # the stage output and are safe to bind directly in later stages.
            output_map = dict(compiled.canonical_to_synthesis)
            output_binding = RegionBinding(stage.name, output_region, output_map)
            catalog[stage.name] = output_binding
            results.append(StageResult(stage, compiled, region, output_binding))

        return SynthesisWorkflowResult(initial_names, tuple(results), catalog)

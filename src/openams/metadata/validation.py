"""Semantic validation for normalized OpenAMS metadata."""

from __future__ import annotations

from .errors import MetadataValidationError
from .model import ProjectInputs, TechnologyConfig

_SUPPORTED_PROVIDERS = frozenset(
    {
        "mos_inverse_table",
        "mos_mlp",
        "mos_compare",
    }
)


def validate_technology_config(config: TechnologyConfig) -> None:
    """Validate provider identifiers without interpreting provider sources."""

    for name, source in config.sources.items():
        if source.provider not in _SUPPORTED_PROVIDERS:
            supported = ", ".join(sorted(_SUPPORTED_PROVIDERS))
            raise MetadataValidationError(
                f"unsupported technology provider {source.provider!r} "
                f"for source {name!r}; supported providers: {supported}"
            )


def validate_project_inputs(project: ProjectInputs) -> None:
    """Validate invariants spanning normalized project metadata."""

    if project.technology.active_source not in project.technology.sources:
        raise MetadataValidationError(
            "active technology source is not present in technology sources"
        )

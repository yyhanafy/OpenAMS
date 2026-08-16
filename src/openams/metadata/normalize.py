"""Normalization from generic mappings to semantic metadata objects."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import MetadataValidationError
from .model import ProjectInputs, TechnologyConfig, TechnologySourceConfig
from .validation import validate_project_inputs, validate_technology_config


def _require_mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MetadataValidationError(f"{name} must be a mapping")
    return value


def normalize_technology_config(
    design_rules: Mapping[str, Any],
) -> TechnologyConfig:
    """Normalize the canonical technology declaration from design rules."""

    rules = _require_mapping(design_rules, name="design_rules")

    if "technology" in rules:
        raise MetadataValidationError(
            "legacy top-level 'technology' is unsupported; use "
            "'active_technology_source' and 'technology_sources'"
        )

    active = rules.get("active_technology_source")
    sources_document = rules.get("technology_sources")

    if not isinstance(active, str) or not active.strip():
        raise MetadataValidationError(
            "design rules require non-empty 'active_technology_source'"
        )
    if not isinstance(sources_document, Mapping) or not sources_document:
        raise MetadataValidationError(
            "design rules require non-empty 'technology_sources' mapping"
        )

    sources: dict[str, TechnologySourceConfig] = {}
    for name, entry in sources_document.items():
        if not isinstance(name, str) or not name.strip():
            raise MetadataValidationError(
                "technology source names must be non-empty strings"
            )
        if not isinstance(entry, Mapping):
            raise MetadataValidationError(
                f"technology source {name!r} must be a mapping"
            )

        provider = entry.get("provider")
        source = entry.get("source")
        if not isinstance(provider, str) or not provider.strip():
            raise MetadataValidationError(
                f"technology source {name!r} requires string 'provider'"
            )
        if not isinstance(source, str) or not source.strip():
            raise MetadataValidationError(
                f"technology source {name!r} requires string 'source'"
            )

        options = {
            key: value
            for key, value in entry.items()
            if key not in {"provider", "source"}
        }
        sources[name] = TechnologySourceConfig(
            name=name,
            provider=provider,
            source=source,
            options=options,
        )

    try:
        config = TechnologyConfig(active_source=active, sources=sources)
    except ValueError as exc:
        raise MetadataValidationError(str(exc)) from exc

    validate_technology_config(config)
    return config


def normalize_project_inputs(
    *,
    specifications: Mapping[str, Any],
    design_intent: Mapping[str, Any],
    design_rules: Mapping[str, Any],
    simulation: Mapping[str, Any],
) -> ProjectInputs:
    """Normalize the complete semantic metadata boundary."""

    specs = _require_mapping(specifications, name="specifications")
    intent = _require_mapping(design_intent, name="design_intent")
    rules = _require_mapping(design_rules, name="design_rules")
    sim = _require_mapping(simulation, name="simulation")

    project = ProjectInputs(
        specifications=specs,
        design_intent=intent,
        design_rules=rules,
        simulation=sim,
        technology=normalize_technology_config(rules),
    )
    validate_project_inputs(project)
    return project

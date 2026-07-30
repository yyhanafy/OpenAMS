"""Semantic metadata normalization for OpenAMS."""

from .errors import MetadataError, MetadataValidationError
from .model import ProjectInputs, TechnologyConfig, TechnologySourceConfig
from .normalize import normalize_project_inputs, normalize_technology_config
from .validation import validate_project_inputs, validate_technology_config

__all__ = [
    "MetadataError",
    "MetadataValidationError",
    "ProjectInputs",
    "TechnologyConfig",
    "TechnologySourceConfig",
    "normalize_project_inputs",
    "normalize_technology_config",
    "validate_project_inputs",
    "validate_technology_config",
]

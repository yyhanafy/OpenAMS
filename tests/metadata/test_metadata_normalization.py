from types import MappingProxyType

import pytest

from openams.metadata import (
    MetadataValidationError,
    normalize_project_inputs,
    normalize_technology_config,
)


def _rules() -> dict:
    return {
        "active_technology_source": "sky130_tt_27c",
        "technology_sources": {
            "sky130_tt_27c": {
                "provider": "mos_inverse_table",
                "source": "technology/sky130_tt_27c.csv",
                "corner": "tt",
                "temperature_c": 27,
            }
        },
    }


def test_normalize_project_inputs_has_no_filesystem_dependency() -> None:
    project = normalize_project_inputs(
        specifications={"specifications": []},
        design_intent={"constraints": []},
        design_rules=_rules(),
        simulation={"analyses": []},
    )

    assert project.technology.active.provider == "mos_inverse_table"
    assert project.technology.active.source == "technology/sky130_tt_27c.csv"
    assert project.technology.active.options["corner"] == "tt"
    assert isinstance(project.specifications, MappingProxyType)


def test_normalized_nested_values_are_immutable() -> None:
    project = normalize_project_inputs(
        specifications={"groups": [{"name": "performance"}]},
        design_intent={"constraints": []},
        design_rules=_rules(),
        simulation={"analyses": []},
    )

    with pytest.raises(TypeError):
        project.specifications["new"] = 1
    with pytest.raises(TypeError):
        project.specifications["groups"][0]["name"] = "changed"


def test_metadata_does_not_check_source_existence() -> None:
    rules = _rules()
    rules["technology_sources"]["sky130_tt_27c"]["source"] = "/not/a/real/file.csv"

    config = normalize_technology_config(rules)

    assert config.active.source == "/not/a/real/file.csv"


def test_legacy_technology_shape_is_rejected() -> None:
    with pytest.raises(MetadataValidationError, match="legacy top-level"):
        normalize_technology_config(
            {"technology": {"provider": "mos_inverse_table"}}
        )


def test_unknown_active_source_is_rejected() -> None:
    rules = _rules()
    rules["active_technology_source"] = "missing"

    with pytest.raises(MetadataValidationError, match="not declared"):
        normalize_technology_config(rules)


def test_unsupported_provider_is_rejected() -> None:
    rules = _rules()
    rules["technology_sources"]["sky130_tt_27c"]["provider"] = "unknown"

    with pytest.raises(
        MetadataValidationError,
        match="unsupported technology provider",
    ):
        normalize_technology_config(rules)


def test_project_documents_must_be_mappings() -> None:
    with pytest.raises(MetadataValidationError, match="specifications"):
        normalize_project_inputs(
            specifications=[],
            design_intent={},
            design_rules=_rules(),
            simulation={},
        )

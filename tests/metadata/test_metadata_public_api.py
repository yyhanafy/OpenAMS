def test_metadata_public_api() -> None:
    import openams.metadata as metadata

    expected = {
        "MetadataError",
        "MetadataValidationError",
        "ProjectInputs",
        "TechnologyConfig",
        "TechnologySourceConfig",
        "normalize_project_inputs",
        "normalize_technology_config",
        "validate_project_inputs",
        "validate_technology_config",
    }
    assert expected == set(metadata.__all__)

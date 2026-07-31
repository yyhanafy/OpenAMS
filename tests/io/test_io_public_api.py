def test_io_public_api() -> None:
    import openams.io as io

    expected = {
        "InputError",
        "LoadedCharacterizationCsv",
        "LoadedSpiceHierarchy",
        "ProjectPaths",
        "SerializationDependencyError",
        "load_characterization_csv",
        "load_spice_hierarchy",
        "load_yaml_mapping",
        "validate_project_paths",
    }
    assert expected == set(io.__all__)

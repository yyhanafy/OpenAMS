def test_table_public_api() -> None:
    import openams.technology.table as table

    assert set(table.__all__) == {
        "BracketAxis",
        "BracketResult",
        "CharacterizationTable",
        "DuplicateCharacterizationPointError",
        "TableLookupError",
        "TableTechnologyBackend",
        "TableValidationError",
        "bracket_points",
        "exact_point",
        "nearest_points",
        "points_for_model",
        "validate_characterization_table",
    }

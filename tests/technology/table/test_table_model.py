import pytest

from openams.technology.table import (
    BracketAxis,
    BracketResult,
    CharacterizationTable,
    DuplicateCharacterizationPointError,
)


def test_table_is_immutable(characterization_table: CharacterizationTable) -> None:
    assert isinstance(characterization_table.points, tuple)
    assert characterization_table.points[0].source == "fixture"

    with pytest.raises(Exception):
        characterization_table.points = ()


def test_duplicate_exact_points_are_rejected(
    characterization_table: CharacterizationTable,
) -> None:
    point = characterization_table.points[0]
    with pytest.raises(DuplicateCharacterizationPointError, match="duplicate"):
        CharacterizationTable(
            identity=characterization_table.identity,
            capabilities=characterization_table.capabilities,
            points=(point, point),
        )


def test_bracket_result_properties(characterization_table) -> None:
    point = characterization_table.points[0]
    exact = BracketResult(
        axis=BracketAxis.WIDTH,
        target=1e-6,
        lower=point,
        upper=point,
    )
    assert exact.is_exact
    assert exact.is_complete

import pytest

from openams.technology import (
    CharacterizationPoint,
    DevicePolarity,
    TechnologyQuantity,
)
from openams.technology.table import (
    CharacterizationTable,
    TableValidationError,
    validate_characterization_table,
)


def test_table_point_quantities_must_be_declared(
    characterization_table,
) -> None:
    original = characterization_table.points[0]
    invalid = CharacterizationPoint(
        operating_point=original.operating_point,
        values={
            TechnologyQuantity.ID: 1e-6,
            TechnologyQuantity.GM: 1e-5,
        },
        region=original.region,
        source=original.source,
    )
    table = CharacterizationTable(
        identity=characterization_table.identity,
        capabilities=characterization_table.capabilities,
        points=(invalid,),
    )

    with pytest.raises(TableValidationError, match="undeclared"):
        validate_characterization_table(table)


def test_valid_table_passes_validation(characterization_table) -> None:
    assert (
        validate_characterization_table(characterization_table)
        is characterization_table
    )

import pytest

from openams.constraints import (
    ConstraintSet,
    ConstraintValidationError,
    validate_constraint_set,
)


def test_explicit_validation_boundary() -> None:
    empty = ConstraintSet(name="empty", constraints=())
    assert validate_constraint_set(empty) is empty

    with pytest.raises(ConstraintValidationError, match="must not be empty"):
        validate_constraint_set(empty, allow_empty=False)

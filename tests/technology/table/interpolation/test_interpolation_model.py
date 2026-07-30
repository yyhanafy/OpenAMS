import pytest

from openams.technology.table.interpolation import (
    DEFAULT_INTERPOLATION_AXES,
    InterpolationAxis,
    InterpolationPolicy,
    InterpolationStep,
)


def test_default_axis_order_is_stable() -> None:
    assert DEFAULT_INTERPOLATION_AXES == (
        InterpolationAxis.TEMPERATURE,
        InterpolationAxis.LENGTH,
        InterpolationAxis.WIDTH,
        InterpolationAxis.VBS,
        InterpolationAxis.VDS,
        InterpolationAxis.VGS,
    )


def test_policy_rejects_duplicate_axes() -> None:
    with pytest.raises(ValueError, match="unique"):
        InterpolationPolicy(
            axes=(InterpolationAxis.WIDTH, InterpolationAxis.WIDTH)
        )


def test_step_validates_alpha() -> None:
    with pytest.raises(ValueError, match="alpha"):
        InterpolationStep(
            axis=InterpolationAxis.WIDTH,
            target=2.0,
            lower=1.0,
            upper=3.0,
            alpha=1.5,
        )

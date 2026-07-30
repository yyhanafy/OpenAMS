def test_interpolation_public_api() -> None:
    import openams.technology.table.interpolation as interpolation

    assert set(interpolation.__all__) == {
        "DEFAULT_INTERPOLATION_AXES",
        "IncompatibleOperatingRegionError",
        "InterpolatingTableTechnologyBackend",
        "InterpolationAxis",
        "InterpolationError",
        "InterpolationGridError",
        "InterpolationOutOfRangeError",
        "InterpolationPolicy",
        "InterpolationStep",
        "interpolate_request",
    }

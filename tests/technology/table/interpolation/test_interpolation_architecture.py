from pathlib import Path


def test_interpolation_has_no_pdk_or_external_numeric_dependencies() -> None:
    root = (
        Path(__file__).parents[4]
        / "src"
        / "openams"
        / "technology"
        / "table"
        / "interpolation"
    )
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.glob("*.py")
    )

    forbidden = (
        "openams.topology",
        "openams.constraints",
        "openams.planning",
        "openams.synthesis",
        "openams.simulation",
        "openams.evaluation",
        "openams.optimization",
        "sky130",
        "pandas",
        "numpy",
        "scipy",
        "torch",
        "ngspice",
        "csv",
        "subprocess",
        "eval(",
        "exec(",
    )
    for token in forbidden:
        assert token not in text

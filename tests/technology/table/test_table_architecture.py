from pathlib import Path


def test_table_backend_has_no_external_numeric_or_pdk_dependencies() -> None:
    root = Path(__file__).parents[3] / "src" / "openams" / "technology" / "table"
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

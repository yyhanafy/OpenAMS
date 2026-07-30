from pathlib import Path


def test_technology_is_independent_of_circuit_execution_layers() -> None:
    root = Path(__file__).parents[2] / "src" / "openams" / "technology"
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
        "pandas",
        "numpy",
        "scipy",
        "torch",
        "ngspice",
        "csv",
        "Path(",
        "subprocess",
        "eval(",
        "exec(",
    )
    for token in forbidden:
        assert token not in text

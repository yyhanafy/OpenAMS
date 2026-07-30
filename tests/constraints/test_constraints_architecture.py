from pathlib import Path


def test_constraints_do_not_solve_or_access_lower_services() -> None:
    root = Path(__file__).parents[2] / "src" / "openams" / "constraints"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.glob("*.py")
    )

    forbidden = (
        "openams.planning",
        "openams.synthesis",
        "openams.technology",
        "openams.simulation",
        "openams.evaluation",
        "openams.optimization",
        "numpy",
        "scipy",
        "sympy",
        "eval(",
        "exec(",
        "Path(",
    )
    for token in forbidden:
        assert token not in text

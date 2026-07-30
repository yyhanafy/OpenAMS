from pathlib import Path


def test_planning_does_not_execute_downstream_work() -> None:
    root = Path(__file__).parents[2] / "src" / "openams" / "planning"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.glob("*.py")
    )

    forbidden = (
        "openams.synthesis",
        "openams.technology",
        "openams.simulation",
        "openams.optimization",
        "subprocess",
        "ngspice",
        "numpy",
        "scipy",
        "torch",
        "botorch",
        "eval(",
        "exec(",
        "Path(",
    )
    for token in forbidden:
        assert token not in text

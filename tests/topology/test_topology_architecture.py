from pathlib import Path


def test_topology_has_no_filesystem_or_technology_access() -> None:
    root = Path(__file__).parents[2] / "src" / "openams" / "topology"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.glob("*.py")
    )
    assert "openams.io" not in text
    assert "openams.technology" not in text
    assert "openams.simulation" not in text
    assert "Path(" not in text

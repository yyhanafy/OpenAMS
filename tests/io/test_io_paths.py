from pathlib import Path

import pytest

from openams.io import InputError, ProjectPaths, validate_project_paths


def _write(path: Path) -> Path:
    path.write_text("test\n", encoding="utf-8")
    return path


def test_project_paths_validate_regular_files(tmp_path: Path) -> None:
    paths = ProjectPaths(
        netlist=_write(tmp_path / "circuit.spice"),
        specifications=_write(tmp_path / "specs.yaml"),
        design_intent=_write(tmp_path / "intent.yaml"),
        design_rules=_write(tmp_path / "rules.yaml"),
        simulation=_write(tmp_path / "simulation.yaml"),
    )

    validate_project_paths(paths)


def test_project_paths_reject_missing_input(tmp_path: Path) -> None:
    existing = _write(tmp_path / "existing")
    paths = ProjectPaths(
        netlist=existing,
        specifications=existing,
        design_intent=existing,
        design_rules=existing,
        simulation=tmp_path / "missing.yaml",
    )

    with pytest.raises(InputError, match="simulation"):
        validate_project_paths(paths)

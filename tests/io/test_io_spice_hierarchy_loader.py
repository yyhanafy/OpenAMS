from pathlib import Path

import pytest

from openams.io import InputError, load_spice_hierarchy


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_loads_recursive_include_tree(tmp_path: Path) -> None:
    write(
        tmp_path / "leaf.spice",
        ".subckt leaf a b\nR1 a b 1k\n.ends leaf\n",
    )
    write(
        tmp_path / "middle.spice",
        '.include "leaf.spice"\n'
        ".subckt middle a b\nX1 a b leaf\n.ends middle\n",
    )
    write(
        tmp_path / "top.spice",
        '.include "middle.spice"\n'
        ".subckt top a b\nX1 a b middle\n.ends top\n",
    )

    loaded = load_spice_hierarchy(tmp_path / "top.spice")

    assert len(loaded.sources) == 3
    assert loaded.source_paths[0].endswith("top.spice")
    assert loaded.source_paths[1].endswith("middle.spice")
    assert loaded.source_paths[2].endswith("leaf.spice")


def test_recovers_stale_absolute_include_by_basename(tmp_path: Path) -> None:
    write(
        tmp_path / "child.spice",
        ".subckt child a b\nR1 a b 1k\n.ends child\n",
    )
    write(
        tmp_path / "top.spice",
        '.include "/stale/path/child.spice"\n'
        ".subckt top a b\nX1 a b child\n.ends top\n",
    )

    loaded = load_spice_hierarchy(
        tmp_path / "top.spice",
        include_search_roots=(tmp_path,),
    )

    assert len(loaded.sources) == 2


def test_missing_include_is_explicit(tmp_path: Path) -> None:
    write(
        tmp_path / "top.spice",
        '.include "missing.spice"\n'
        ".subckt top a b\nR1 a b 1k\n.ends top\n",
    )

    with pytest.raises(InputError, match="could not be resolved"):
        load_spice_hierarchy(tmp_path / "top.spice")

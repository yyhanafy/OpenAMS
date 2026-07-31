from pathlib import Path

from openams.io import (
    LoadedCharacterizationCsv,
    load_characterization_csv,
)


def test_loads_raw_characterization_csv(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    path.write_text(
        "polarity,model,corner\n"
        "nmos,nfet,tt\n",
        encoding="utf-8",
    )

    loaded = load_characterization_csv(path)

    assert isinstance(loaded, LoadedCharacterizationCsv)
    assert loaded.fieldnames == ("polarity", "model", "corner")
    assert loaded.rows[0]["model"] == "nfet"

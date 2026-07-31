from pathlib import Path

import pytest

from openams.adapters import load_characterization_table_csv
from openams.io import InputError
from openams.technology import (
    DevicePolarity,
    OperatingRegion,
    TechnologyQuantity,
)


def test_builds_characterization_table(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    path.write_text(
        "polarity,model,corner,temperature_c,length_um,width_um,"
        "vgs_abs_v,vds_abs_v,vbs_abs_v,id_abs_a,vdsat_abs_v,"
        "vth_abs_v,gm_s,gds_s,saturated\n"
        "nmos,nfet,tt,27,0.5,1.0,0.8,0.8,0.0,"
        "1e-5,0.2,0.6,2e-4,1e-6,1\n"
        "pmos,pfet,tt,27,0.5,2.0,0.8,0.8,0.0,"
        "2e-5,0.21,0.61,3e-4,2e-6,0\n",
        encoding="utf-8",
    )

    table = load_characterization_table_csv(path)

    assert len(table.points) == 2
    assert table.capabilities.polarities == {
        DevicePolarity.NMOS,
        DevicePolarity.PMOS,
    }
    assert TechnologyQuantity.GM in table.capabilities.quantities
    assert table.points[0].region is OperatingRegion.SATURATION


def test_missing_required_column_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("polarity,model\nnmos,nfet\n", encoding="utf-8")

    with pytest.raises(InputError, match="missing required columns"):
        load_characterization_table_csv(path)

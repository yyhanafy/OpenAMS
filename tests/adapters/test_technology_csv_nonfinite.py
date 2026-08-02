from pathlib import Path

from openams.adapters import load_characterization_table_csv
from openams.technology import TechnologyQuantity


def test_nonfinite_optional_metrics_are_omitted(tmp_path: Path) -> None:
    path = tmp_path / "dense_like.csv"
    path.write_text(
        "polarity,model,corner,temperature_c,length_um,width_um,"
        "vgs_abs_v,vds_abs_v,vbs_abs_v,id_abs_a,vdsat_abs_v,"
        "vth_abs_v,gm_s,gds_s,saturated\n"
        "nmos,nfet,tt,27,0.5,1.0,0.8,0.8,0.0,"
        "1e-5,0.2,nan,2e-4,inf,1\n",
        encoding="utf-8",
    )

    table = load_characterization_table_csv(path)
    point = table.points[0]

    assert point.values[TechnologyQuantity.ID] == 1e-5
    assert point.values[TechnologyQuantity.VDSAT] == 0.2
    assert point.values[TechnologyQuantity.GM] == 2e-4
    assert TechnologyQuantity.VTH not in point.values
    assert TechnologyQuantity.GDS not in point.values

"""Dense-table capacitance lookup for temporary hybrid MLP/table AC estimates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


@dataclass(frozen=True)
class DeviceCapacitances:
    cgs_f: float
    cgd_f: float
    cdb_f: float
    csb_f: float
    distance: float
    source: str = "dense_table_nearest_bias_capacitance_density"


class DenseCapacitanceLookup:
    """Nearest-bias capacitance-density lookup, scaled to requested width."""

    REQUIRED = (
        "polarity",
        "length_um",
        "width_um",
        "vgs_abs_v",
        "vds_abs_v",
        "vbs_abs_v",
        "cgs_f",
        "cgd_f",
        "cdb_f",
        "csb_f",
    )

    def __init__(self, table_path: Path, *, length_um: float = 0.5):
        frame = pd.read_csv(table_path, usecols=list(self.REQUIRED))
        for name in self.REQUIRED[1:]:
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
        frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
        frame = frame[frame["width_um"] > 0.0]
        frame = frame[np.isclose(frame["length_um"], length_um)]

        for cap in ("cgs_f", "cgd_f", "cdb_f", "csb_f"):
            frame[f"{cap}_per_um"] = frame[cap] / frame["width_um"]

        # Average width-normalized capacitance at the same electrical bias.
        grouped = (
            frame.groupby(
                ["polarity", "vgs_abs_v", "vds_abs_v", "vbs_abs_v"],
                as_index=False,
            )[
                [
                    "cgs_f_per_um",
                    "cgd_f_per_um",
                    "cdb_f_per_um",
                    "csb_f_per_um",
                ]
            ]
            .mean()
        )

        self._data = {}
        for polarity in ("nmos", "pmos"):
            part = grouped[grouped["polarity"] == polarity].copy()
            if part.empty:
                raise ValueError(f"no capacitance rows for {polarity}")
            features = part[["vgs_abs_v", "vds_abs_v", "vbs_abs_v"]].to_numpy()
            # Voltage dimensions use the same units and similar ranges.
            tree = cKDTree(features)
            self._data[polarity] = (part.reset_index(drop=True), tree)

    def lookup(
        self,
        *,
        polarity: str,
        width_um: float,
        vgs_abs_v: float,
        vds_abs_v: float,
        vbs_abs_v: float = 0.0,
    ) -> DeviceCapacitances:
        part, tree = self._data[polarity.lower()]
        distance, index = tree.query([vgs_abs_v, vds_abs_v, vbs_abs_v], k=1)
        row = part.iloc[int(index)]

        def scaled(name: str) -> float:
            # Numerical characterization may produce signed matrix entries.
            # For the reduced Cgs/Cgd/Cdb/Csb model, use magnitude.
            return abs(float(row[f"{name}_per_um"])) * width_um

        return DeviceCapacitances(
            cgs_f=scaled("cgs_f"),
            cgd_f=scaled("cgd_f"),
            cdb_f=scaled("cdb_f"),
            csb_f=scaled("csb_f"),
            distance=float(distance),
        )

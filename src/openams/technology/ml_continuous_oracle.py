from __future__ import annotations
import csv, hashlib, json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from openams.technology.ml_surrogate.predictor import MosMlpBundle

@dataclass(frozen=True)
class ContinuousMosPoint:
    polarity: str
    width_um: float
    length_um: float
    vgs_abs_v: float
    vds_abs_v: float
    vbs_abs_v: float
    id_abs_a: float
    vdsat_abs_v: float
    vth_abs_v: float
    gm_s: float
    gds_s: float
    saturated: bool
    in_domain: bool
    source: str = "mos_mlp"

class AdaptiveMosCache:
    FIELDS = ["key","polarity","width_um","length_um","vgs_abs_v","vds_abs_v",
              "vbs_abs_v","id_abs_a","vdsat_abs_v","vth_abs_v","gm_s","gds_s",
              "saturated","in_domain","source"]
    def __init__(self, path: Path):
        self.path = path
        self.rows = {}
        self.dirty = False
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    self.rows[row["key"]] = row
    @staticmethod
    def key_for(**values: Any) -> str:
        raw = json.dumps(values, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:24]
    def put_memory(self, key: str, point: ContinuousMosPoint) -> None:
        self.rows[key] = {"key": key, **{k: str(v) for k, v in asdict(point).items()}}
        self.dirty = True
    def flush(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.FIELDS)
            w.writeheader()
            for key in sorted(self.rows):
                w.writerow(self.rows[key])
        self.dirty = False

class MlpContinuousTechnologyOracle:
    def __init__(self, checkpoints, cache_path: Path, saturation_margin_v: float = 0.0):
        self.bundle = MosMlpBundle.load(checkpoints)
        self.cache = AdaptiveMosCache(cache_path)
        self.saturation_margin_v = saturation_margin_v
        self.query_count = 0
        self.cache_hits = 0
    def predict(self, *, polarity: str, width_um: float, length_um: float,
                vgs_abs_v: float, vds_abs_v: float, vbs_abs_v: float = 0.0,
                allow_extrapolation: bool = False, persist: bool = False):
        self.query_count += 1
        pred = self.bundle.predict(
            polarity=polarity, width_um=width_um, length_um=length_um,
            vgs_abs_v=vgs_abs_v, vds_abs_v=vds_abs_v, vbs_abs_v=vbs_abs_v,
            saturation_margin_v=self.saturation_margin_v,
            allow_extrapolation=allow_extrapolation,
        )
        model = self.bundle.models[polarity.lower()]
        point = ContinuousMosPoint(
            polarity=polarity.lower(), width_um=float(width_um),
            length_um=float(length_um), vgs_abs_v=float(vgs_abs_v),
            vds_abs_v=float(vds_abs_v), vbs_abs_v=float(vbs_abs_v),
            id_abs_a=float(pred.id_abs_a), vdsat_abs_v=float(pred.vdsat_abs_v),
            vth_abs_v=float(pred.vth_abs_v), gm_s=float(pred.gm_s),
            gds_s=float(pred.gds_s), saturated=bool(pred.saturated),
            in_domain=model.in_domain(width_um=width_um, length_um=length_um,
                                     vgs_abs_v=vgs_abs_v, vds_abs_v=vds_abs_v,
                                     vbs_abs_v=vbs_abs_v),
        )
        if persist:
            key = self.cache.key_for(
                polarity=point.polarity, width_um=round(point.width_um, 10),
                length_um=round(point.length_um, 10), vgs_abs_v=round(point.vgs_abs_v, 10),
                vds_abs_v=round(point.vds_abs_v, 10), vbs_abs_v=round(point.vbs_abs_v, 10),
                saturation_margin_v=round(self.saturation_margin_v, 10))
            self.cache.put_memory(key, point)
        return point
    def flush_cache(self) -> None:
        self.cache.flush()

#!/usr/bin/env python3
"""
Characterize the legal Laygo2 SKY130 MOS nf space.

For each requested nf:
- load the installed SKY130 Laygo2 templates
- generate native nmos / pmos virtual instances
- record success/failure
- record bbox/unit size
- record pin names/geometry
- inspect native elements, especially IM0 core shape
- flag whether odd nf silently aliases to the same physical core as a nearby even nf

Outputs CSV and JSON suitable for OpenAMS quantization logic.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def import_module_from_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def arr_to_list(x):
    if x is None:
        return None
    try:
        return x.tolist()
    except Exception:
        try:
            return list(x)
        except Exception:
            return str(x)


def inspect_instance(inst, nf_requested: int, polarity: str) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "polarity": polarity,
        "nf_requested": nf_requested,
        "success": True,
        "error": None,
    }

    row["bbox"] = arr_to_list(getattr(inst, "bbox", None))
    row["xy"] = arr_to_list(getattr(inst, "xy", None))
    row["unit_size"] = arr_to_list(getattr(inst, "unit_size", None))
    row["size"] = arr_to_list(getattr(inst, "size", None))
    row["pitch"] = arr_to_list(getattr(inst, "pitch", None))

    pins = getattr(inst, "pins", {}) or {}
    row["pin_names"] = sorted(str(k) for k in pins.keys())
    row["pins"] = {}
    for k, p in pins.items():
        row["pins"][str(k)] = {
            "xy": arr_to_list(getattr(p, "xy", None)),
            "layer": arr_to_list(getattr(p, "layer", None)),
            "netname": getattr(p, "netname", None),
        }

    native = getattr(inst, "native_elements", {}) or {}
    row["native_element_names"] = sorted(str(k) for k in native.keys())

    core = native.get("IM0")
    if core is not None:
        row["core_cellname"] = getattr(core, "cellname", None)
        row["core_shape"] = arr_to_list(getattr(core, "shape", None))
        row["core_pitch"] = arr_to_list(getattr(core, "pitch", None))
        row["core_unit_size"] = arr_to_list(getattr(core, "unit_size", None))
    else:
        row["core_cellname"] = None
        row["core_shape"] = None
        row["core_pitch"] = None
        row["core_unit_size"] = None

    # Useful scalar for detecting aliasing.
    bbox = row.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 2 and len(bbox[0]) == 2 and len(bbox[1]) == 2:
        row["bbox_width"] = bbox[1][0] - bbox[0][0]
        row["bbox_height"] = bbox[1][1] - bbox[0][1]
    else:
        row["bbox_width"] = None
        row["bbox_height"] = None

    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="~/AMS-Tutorial/laygo2_workspace_sky130")
    ap.add_argument(
        "--nf",
        nargs="*",
        type=int,
        default=[1,2,3,4,5,6,7,8,9,10,12,16,20,24,32,40,48,64],
        help="nf values to test",
    )
    ap.add_argument(
        "--output-dir",
        default="runtime/laygo2_quantization_space/nf_characterization",
    )
    args = ap.parse_args()

    ws = Path(args.workspace).expanduser().resolve()
    tech_dir = ws / "skywater130" / "laygo2_tech"
    templates_py = tech_dir / "laygo2_tech_templates.py"
    if not templates_py.is_file():
        raise SystemExit(f"Missing {templates_py}")

    # Make workspace/local Laygo2 importable.
    sys.path.insert(0, str(ws / "laygo2"))
    sys.path.insert(0, str(ws))
    sys.path.insert(0, str(ws / "skywater130"))
    sys.path.insert(0, str(tech_dir))

    # The SKY130 technology module opens:
    #     ./laygo2_tech/laygo2_tech.yaml
    # using a path relative to the *skywater130* directory.
    #
    # Therefore import it with cwd = <workspace>/skywater130,
    # not <workspace>/skywater130/laygo2_tech.
    old_cwd = Path.cwd()
    try:
        import os
        os.chdir(ws / "skywater130")
        mod = import_module_from_file(templates_py, "openams_sky130_templates")
        tlib = mod.load_templates()
    finally:
        os.chdir(old_cwd)

    outdir = Path(args.output_dir).expanduser()
    if not outdir.is_absolute():
        outdir = (old_cwd / outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    print("===== LAYGO2 SKY130 NF CHARACTERIZATION =====")
    print("workspace:", ws)
    print("nf sweep :", args.nf)
    print()

    rows: List[Dict[str, Any]] = []

    for polarity in ("nmos", "pmos"):
        if polarity not in tlib:
            raise SystemExit(f"Template '{polarity}' not found in loaded template library")

        template = tlib[polarity]

        print(f"===== {polarity.upper()} =====")
        for nf in args.nf:
            try:
                inst = template.generate(
                    name=f"M_{polarity}_{nf}",
                    params={
                        "nf": nf,
                        "nfdmyl": 0,
                        "nfdmyr": 0,
                        "bndl": True,
                        "bndr": True,
                        "gbndl": False,
                        "gbndr": False,
                        "trackswap": False,
                        "tie": None,
                    },
                )
                row = inspect_instance(inst, nf, polarity)
                cs = row.get("core_shape")
                print(
                    f"nf={nf:>3d} PASS "
                    f"bbox=({row.get('bbox_width')},{row.get('bbox_height')}) "
                    f"core_shape={cs} "
                    f"pins={','.join(row.get('pin_names', []))}"
                )
            except Exception as e:
                row = {
                    "polarity": polarity,
                    "nf_requested": nf,
                    "success": False,
                    "error": f"{type(e).__name__}: {e}",
                    "bbox": None,
                    "xy": None,
                    "unit_size": None,
                    "size": None,
                    "pitch": None,
                    "pin_names": [],
                    "pins": {},
                    "native_element_names": [],
                    "core_cellname": None,
                    "core_shape": None,
                    "core_pitch": None,
                    "core_unit_size": None,
                    "bbox_width": None,
                    "bbox_height": None,
                }
                print(f"nf={nf:>3d} FAIL {row['error']}")
            rows.append(row)
        print()

    # Detect same-polarity physical aliasing based on bbox/core shape.
    for pol in ("nmos", "pmos"):
        pol_rows = [r for r in rows if r["polarity"] == pol and r["success"]]
        groups = {}
        for r in pol_rows:
            key = (
                json.dumps(r.get("core_shape"), sort_keys=True),
                r.get("bbox_width"),
                r.get("bbox_height"),
                tuple(r.get("pin_names", [])),
            )
            groups.setdefault(key, []).append(r["nf_requested"])

        print(f"===== {pol.upper()} PHYSICAL ALIAS GROUPS =====")
        for nfs in groups.values():
            if len(nfs) > 1:
                print("same generated geometry for nf:", nfs)
        print()

    # JSON
    json_path = outdir / "laygo2_nf_characterization.json"
    json_path.write_text(json.dumps({
        "workspace": str(ws),
        "nf_values": args.nf,
        "rows": rows,
    }, indent=2))

    # CSV
    csv_path = outdir / "laygo2_nf_characterization.csv"
    fields = [
        "polarity", "nf_requested", "success", "error",
        "bbox_width", "bbox_height",
        "core_cellname", "core_shape",
        "pin_names",
    ]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({
                "polarity": r["polarity"],
                "nf_requested": r["nf_requested"],
                "success": r["success"],
                "error": r["error"] or "",
                "bbox_width": "" if r["bbox_width"] is None else r["bbox_width"],
                "bbox_height": "" if r["bbox_height"] is None else r["bbox_height"],
                "core_cellname": r["core_cellname"] or "",
                "core_shape": json.dumps(r["core_shape"]),
                "pin_names": ",".join(r["pin_names"]),
            })

    print("===== OUTPUTS =====")
    print(csv_path)
    print(json_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

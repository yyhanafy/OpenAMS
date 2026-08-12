#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc

def walk(obj: Any, path=()):
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (str(i),))

def is_template_dict(v):
    return isinstance(v, dict) and "pins" in v and ("xy" in v or "unit_size" in v)

def collect_templates(doc):
    rows = []
    for path, obj in walk(doc):
        if not path or not is_template_dict(obj):
            continue
        name = path[-1]
        lname = name.lower()
        if "nmos" not in lname and "pmos" not in lname:
            continue
        polarity = "nmos" if "nmos" in lname else "pmos"
        m = re.search(r"_nf(\d+)(?:_|$)", lname)
        nf = int(m.group(1)) if m else None
        unit = obj.get("unit_size")
        pins = obj.get("pins") or {}
        rows.append({
            "template": name,
            "polarity": polarity,
            "nf": nf,
            "unit_size_x": unit[0] if isinstance(unit, list) and len(unit) >= 2 else None,
            "unit_size_y": unit[1] if isinstance(unit, list) and len(unit) >= 2 else None,
            "pin_names": sorted(map(str, pins.keys())),
            "pins": pins,
            "bbox": obj.get("xy"),
            "yaml_path": "/" + "/".join(path),
        })
    return sorted(rows, key=lambda r: (r["polarity"], r["nf"] if r["nf"] is not None else 999999, r["template"]))

def collect_grids(doc):
    out = []
    grid_keys = {"xgrid","ygrid","x","y","horizontal","vertical","vextension","hextension","vwidth","hwidth","vlayer","hlayer","viamap","primary_grid"}
    for path, obj in walk(doc):
        if not path or not isinstance(obj, dict):
            continue
        name = path[-1]
        if "grid" not in name.lower():
            continue
        if not (set(obj.keys()) & grid_keys):
            continue
        out.append({"name": name, "yaml_path": "/" + "/".join(path), "keys": sorted(map(str,obj.keys())), "data": obj})
    return out

def choose_yaml(workspace, explicit):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates += [
        workspace/"skywater130"/"laygo2_tech"/"laygo2_tech.yaml",
        workspace/"laygo2_tech"/"laygo2_tech.yaml",
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    raise SystemExit("Could not find laygo2_tech.yaml:\n  " + "\n  ".join(map(str,candidates)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="~/AMS-Tutorial/laygo2_workspace_sky130")
    ap.add_argument("--yaml")
    ap.add_argument("--output-dir", default="runtime/laygo2_quantization_space")
    a = ap.parse_args()

    ws = Path(a.workspace).expanduser().resolve()
    yp = choose_yaml(ws, a.yaml)
    out = Path(a.output_dir).expanduser()
    if not out.is_absolute():
        out = (Path.cwd()/out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    with yp.open() as f:
        doc = yaml.safe_load(f)

    templates = collect_templates(doc)
    grids = collect_grids(doc)
    if not templates:
        raise SystemExit(f"No NMOS/PMOS templates found in {yp}")

    csvp = out/"laygo2_mos_templates.csv"
    with csvp.open("w", newline="") as f:
        fields = ["template","polarity","nf","unit_size_x","unit_size_y","pin_names","yaml_path"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in templates:
            w.writerow({k: (",".join(r[k]) if k=="pin_names" else ("" if r[k] is None else r[k])) for k in fields})

    (out/"laygo2_mos_templates.json").write_text(json.dumps({
        "source_yaml": str(yp), "workspace": str(ws), "template_count": len(templates), "templates": templates
    }, indent=2))
    (out/"laygo2_grid_inventory.json").write_text(json.dumps({
        "source_yaml": str(yp), "grid_count": len(grids), "grids": grids
    }, indent=2))

    nmos = sum(r["polarity"]=="nmos" for r in templates)
    pmos = sum(r["polarity"]=="pmos" for r in templates)
    nfs = sorted({r["nf"] for r in templates if r["nf"] is not None})

    print("===== LAYGO2 SKY130 QUANTIZATION INVENTORY =====")
    print("source yaml :", yp)
    print("templates   :", len(templates))
    print("nmos        :", nmos)
    print("pmos        :", pmos)
    print("nf values   :", nfs)
    print("grids found :", len(grids))
    print("\noutputs:")
    print(" ", csvp)
    print(" ", out/"laygo2_mos_templates.json")
    print(" ", out/"laygo2_grid_inventory.json")
    print("\n===== FIRST MOS TEMPLATES =====")
    for r in templates[:30]:
        print(f"{r['polarity']:4s} nf={str(r['nf']):>4s} size=({r['unit_size_x']},{r['unit_size_y']}) pins={','.join(r['pin_names'])} {r['template']}")

if __name__ == "__main__":
    main()

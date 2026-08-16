#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
import yaml


def load_yaml(path):
    d = yaml.safe_load(path.read_text())
    if not isinstance(d, dict):
        raise ValueError("expected mapping")
    return d


def norm_grid(owner, x):
    g = x["grid"]
    lo, hi, n = float(g["minimum"]), float(g["maximum"]), int(g["count"])
    if n < 2 or hi <= lo:
        raise ValueError(f"{owner}/{x.get('name','?')}: bad grid")
    return {
        "name": x.get("name"),
        "kind": x.get("kind", "scalar"),
        "physical_nodes": list(x.get("physical_nodes", [])),
        "relation": x.get("relation"),
        "grid": {
            "minimum": lo,
            "maximum": hi,
            "count": n,
            "spacing": g.get("spacing", "linear"),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intent", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()

    d = load_yaml(a.intent)
    hf = d.get("hierarchical_feasibility")
    if not isinstance(hf, dict):
        raise ValueError("missing hierarchical_feasibility")

    groups = {
        g["id"]: g for g in d.get("assignment_synthesis", {}).get("groups", [])
        if isinstance(g, dict) and g.get("id")
    }

    components = []
    for c in hf["components"]:
        sg = c.get("source_group", c["id"])
        devices = list(groups.get(sg, {}).get("devices", []))
        rr = c["exact_realizer"]
        components.append({
            "id": c["id"],
            "source_group": sg,
            "devices": devices,
            "depends_on": list(c.get("depends_on", [])),
            "interface_inputs": list(c.get("interface_inputs", [])),
            "interface_outputs": list(c.get("interface_outputs", [])),
            "model": {
                "kind": c["model_kind"],
                "checkpoint": c["checkpoint"],
                "features": list(c.get("mlp_features", [])),
                "emitted_ranges": list(c.get("emitted_ranges", [])),
            },
            "local_search_coordinates": [
                norm_grid(c["id"], x)
                for x in c.get("local_search_coordinates", [])
            ],
            "exact_realizer": {
                **rr,
                "witnesses_per_state": int(
                    rr.get("witnesses_per_state", 3)
                ),
            },
            "derived_after_realization": list(
                c.get("derived_after_realization", [])
            ),
        })

    interfaces = []
    for i in hf["interfaces"]:
        interfaces.append({
            "id": i["id"],
            "between": list(i["between"]),
            "coordinates": [norm_grid(i["id"], x) for x in i["coordinates"]],
            "propagated_variables": list(i.get("propagated_variables", [])),
        })

    ips = hf["independent_point_source"]
    if ips["kind"] == "explicit_grid":
        variables = {}
        for name, spec in ips["variables"].items():
            x = dict(spec)
            x["name"] = name
            variables[name] = norm_grid("independent_point_source", x)
        independent = {"kind": "explicit_grid", "variables": variables}
    elif ips["kind"] == "independent_regions_json":
        independent = dict(ips)
    else:
        raise ValueError(f"unsupported independent source: {ips['kind']}")

    out = {
        "schema_version": 3,
        "strategy": hf["strategy"],
        "independent_point_source": independent,
        "components": components,
        "interfaces": interfaces,
        "final_witness": hf["final_witness"],
    }

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, indent=2) + "\n")

    print("===== HIERARCHICAL COMPONENT CONTRACT V3 =====")
    print("strategy   :", out["strategy"])
    print("components :", len(components))
    for c in components:
        print(" ", c["id"], "->", c["model"]["checkpoint"])
    print("interfaces :", len(interfaces))
    print("independent source:", independent["kind"])
    if independent["kind"] == "explicit_grid":
        total = 1
        for name, spec in independent["variables"].items():
            g = spec["grid"]
            total *= g["count"]
            print(
                f"  {name}: [{g['minimum']},{g['maximum']}] "
                f"x{g['count']} {g['spacing']}"
            )
        print("independent points:", total)
    print("output     :", a.output)


if __name__ == "__main__":
    main()
